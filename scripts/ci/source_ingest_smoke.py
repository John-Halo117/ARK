#!/usr/bin/env python3
"""Bounded source-to-NATS ingestion smoke for ARK.

This test runs the real ingestion-leader binary against local in-process
Redis/NATS protocol fakes. It verifies a real Git commit request reaches the
publish subject without requiring Docker or external services.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

HOST = "127.0.0.1"
REDIS_PORT = 16379
NATS_PORT = 14222
HTTP_ADDR = "127.0.0.1:18080"
SUBJECT = "ark.events.cid"
MAX_SECONDS = 20.0
MAX_REDIS_PARTS = 8
MAX_REDIS_BULK_BYTES = 1_000_000
MAX_NATS_PAYLOAD_BYTES = 16 * 1024 * 1024


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.ready = threading.Event()

    def serve(self) -> None:
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, REDIS_PORT))
        server.listen(8)
        server.settimeout(0.2)
        self.ready.set()
        try:
            for _ in range(100_000):
                if self.stop.is_set():
                    break
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                thread = threading.Thread(target=self.handle, args=(conn,), daemon=True)
                thread.start()
        finally:
            server.close()

    def handle(self, conn: socket.socket) -> None:
        with conn:
            for _ in range(10_000):
                if self.stop.is_set():
                    break
                try:
                    parts = self.read_command(conn)
                except EOFError:
                    break
                except Exception:
                    conn.sendall(b"-ERR invalid command\r\n")
                    break
                self.respond(conn, parts)

    def respond(self, conn: socket.socket, parts: list[str]) -> None:
        cmd = parts[0].upper()
        with self.lock:
            if cmd == "PING":
                conn.sendall(b"+PONG\r\n")
            elif cmd == "GET" and len(parts) == 2:
                value = self.data.get(parts[1])
                if value is None:
                    conn.sendall(b"$-1\r\n")
                else:
                    raw = value.encode()
                    conn.sendall(f"${len(raw)}\r\n".encode() + raw + b"\r\n")
            elif cmd == "SET" and len(parts) == 3:
                self.data[parts[1]] = parts[2]
                conn.sendall(b"+OK\r\n")
            elif cmd == "INCR" and len(parts) == 2:
                next_value = int(self.data.get(parts[1], "0")) + 1
                self.data[parts[1]] = str(next_value)
                conn.sendall(f":{next_value}\r\n".encode())
            else:
                conn.sendall(b"-ERR unsupported command\r\n")

    def read_command(self, conn: socket.socket) -> list[str]:
        first = read_line(conn)
        if not first.startswith("*"):
            raise ValueError("expected redis array")
        count = int(first[1:])
        if count < 1 or count > MAX_REDIS_PARTS:
            raise ValueError("invalid redis array size")
        parts: list[str] = []
        for _ in range(count):
            size_line = read_line(conn)
            if not size_line.startswith("$"):
                raise ValueError("expected redis bulk string")
            size = int(size_line[1:])
            if size < 0 or size > MAX_REDIS_BULK_BYTES:
                raise ValueError("invalid redis bulk size")
            payload = read_exact(conn, size + 2)
            parts.append(payload[:size].decode())
        return parts


class FakeNATS:
    def __init__(self) -> None:
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.published: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def serve(self) -> None:
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, NATS_PORT))
        server.listen(8)
        server.settimeout(0.2)
        self.ready.set()
        try:
            for _ in range(100_000):
                if self.stop.is_set():
                    break
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                thread = threading.Thread(target=self.handle, args=(conn,), daemon=True)
                thread.start()
        finally:
            server.close()

    def handle(self, conn: socket.socket) -> None:
        with conn:
            conn.sendall(
                b'INFO {"server_id":"fake-ark","version":"0.0.0","proto":1,"max_payload":16777216}\r\n'
            )
            buffer = b""
            for _ in range(10_000):
                if self.stop.is_set():
                    break
                try:
                    while b"\r\n" not in buffer:
                        chunk = conn.recv(4096)
                        if not chunk:
                            return
                        buffer += chunk
                    raw_line, buffer = buffer.split(b"\r\n", 1)
                    line = raw_line.decode()
                    if line.startswith("PING"):
                        conn.sendall(b"PONG\r\n")
                    elif line.startswith("CONNECT"):
                        continue
                    elif line.startswith("PUB "):
                        tokens = line.split()
                        if len(tokens) != 3:
                            return
                        subject = tokens[1]
                        size = int(tokens[2])
                        if size < 0 or size > MAX_NATS_PAYLOAD_BYTES:
                            return
                        while len(buffer) < size + 2:
                            chunk = conn.recv(size + 2 - len(buffer))
                            if not chunk:
                                return
                            buffer += chunk
                        payload, buffer = buffer[:size], buffer[size + 2 :]
                        with self.lock:
                            self.published.append(
                                {"subject": subject, "payload": json.loads(payload.decode())}
                            )
                    else:
                        continue
                except Exception:
                    return


def read_line(conn: socket.socket) -> str:
    data = bytearray()
    for _ in range(8192):
        chunk = conn.recv(1)
        if not chunk:
            raise EOFError
        data.extend(chunk)
        if data.endswith(b"\r\n"):
            return bytes(data[:-2]).decode()
    raise ValueError("line exceeds bound")


def read_exact(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def wait_http_ok(url: str, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.3) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"HTTP readiness timed out for {url}")


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    binary = Path(os.environ.get("ARK_INGESTION_LEADER_BIN", "/tmp/ark-ingestion-leader-smoke"))

    subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/ingestion-leader"],
        cwd=root,
        check=True,
        env={
            **os.environ,
            "GOTOOLCHAIN": os.environ.get("GOTOOLCHAIN", "auto"),
            "GOSUMDB": os.environ.get("GOSUMDB", "sum.golang.org"),
        },
    )

    redis = FakeRedis()
    nats = FakeNATS()
    redis_thread = threading.Thread(target=redis.serve, daemon=True)
    nats_thread = threading.Thread(target=nats.serve, daemon=True)
    redis_thread.start()
    nats_thread.start()
    if not redis.ready.wait(2) or not nats.ready.wait(2):
        raise RuntimeError("protocol fakes did not start")

    env = {
        **os.environ,
        "HTTP_ADDR": HTTP_ADDR,
        "REDIS_ADDR": f"{HOST}:{REDIS_PORT}",
        "NATS_URL": f"nats://{HOST}:{NATS_PORT}",
    }
    proc = subprocess.Popen(
        [str(binary)],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_http_ok(f"http://{HTTP_ADDR}/health", MAX_SECONDS)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        body = json.dumps(
            {
                "repo_path": str(root),
                "commit_sha": commit,
                "attributes": {"verification": "source-ingest-smoke"},
            }
        ).encode()
        request = urllib.request.Request(
            f"http://{HTTP_ADDR}/v1/ingest/git-commit",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            http_event = json.loads(response.read().decode())

        deadline = time.time() + MAX_SECONDS
        nats_event = None
        while time.time() < deadline:
            with nats.lock:
                matches = [row for row in nats.published if row["subject"] == SUBJECT]
            if matches:
                nats_event = matches[0]["payload"]
                break
            time.sleep(0.1)
        if nats_event is None:
            raise RuntimeError("ingestion did not publish NATS event")

        required = {"cid", "sequence", "state_hash", "repo", "commit_sha", "author", "occurred_at", "canonical", "stability_ok"}
        missing = sorted(required - set(nats_event))
        if missing:
            raise RuntimeError(f"NATS event missing fields: {missing}")
        if nats_event["cid"] != http_event["cid"] or nats_event["commit_sha"] != commit:
            raise RuntimeError("HTTP event and NATS event mismatch")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "commit_sha": commit[:12],
                    "cid": nats_event["cid"],
                    "sequence": nats_event["sequence"],
                    "subject": SUBJECT,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        redis.stop.set()
        nats.stop.set()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error_code": "SOURCE_INGEST_SMOKE_FAILED", "reason": str(exc), "context": {}, "recoverable": True}))
        raise SystemExit(1)
