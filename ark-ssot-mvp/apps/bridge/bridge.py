import glob
import json
import os
import re
import socket
import ssl
import time
import urllib.request
from datetime import datetime, timezone


HOMEASSISTANT_HOOK = "/ark/homeassistant"
JELLYFIN_HOOK = "/ark/jellyfin"
UNIFI_HOOK = "/ark/unifi"
GENERIC_HOOK = "/ark/event"

STATE_PATH = os.environ.get("ARK_BRIDGE_STATE_PATH", "/state/bridge-state.json")
WEBHOOK_BASE = os.environ.get("ARK_N8N_WEBHOOK_BASE", "http://host.docker.internal:5678/webhook").rstrip("/")
POLL_INTERVAL = max(5, int(os.environ.get("ARK_BRIDGE_POLL_INTERVAL_SECONDS", "15")))
HEALTH_INTERVAL = max(POLL_INTERVAL, int(os.environ.get("ARK_BRIDGE_HEALTH_INTERVAL_SECONDS", "60")))
MAX_LINES_PER_POLL = max(1, int(os.environ.get("ARK_BRIDGE_MAX_LINES_PER_POLL", "25")))

HA_HEALTH_URL = os.environ.get("ARK_HA_HEALTH_URL", "http://homeassistant:8123/")
JELLYFIN_HEALTH_URL = os.environ.get("ARK_JELLYFIN_HEALTH_URL", "http://jellyfin:8096/health")
UNIFI_HEALTH_URL = os.environ.get("ARK_UNIFI_HEALTH_URL", "https://unifi:8443/status")

JELLYFIN_LOG_GLOB = "/sources/jellyfin/log/log_*.log"
UNIFI_LOG_FILES = [
    "/sources/unifi/logs/startup.log",
    "/sources/unifi/logs/server.log",
]

JELLYFIN_LINE_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\] \[(?P<level>[A-Z]+)\] \[(?P<thread>[^\]]+)\] (?P<component>[^:]+): (?P<message>.*)$"
)
UNIFI_LINE_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\] <(?P<thread>[^>]+)> (?P<level>[A-Z]+)\s+(?P<component>[A-Za-z0-9_-]+)\s+- (?P<message>.*)$"
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {"logs": {}, "health": {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def post_json(path, payload):
    request = urllib.request.Request(
        WEBHOOK_BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()
        return response.status


def request_health(url):
    context = ssl._create_unverified_context() if url.startswith("https://") else None
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=8, context=context) as response:
        body = response.read(256).decode("utf-8", errors="replace")
        return {"reachable": True, "status_code": response.status, "body": body}


def emit_health(state, service, url):
    health_key = f"health::{service}"
    last_sent = float(state.get("health", {}).get(health_key, 0))
    now = time.time()
    if now - last_sent < HEALTH_INTERVAL:
        return

    try:
        result = request_health(url)
        classifier_status = "known"
    except Exception as exc:
        result = {"reachable": False, "status_code": 0, "body": str(exc)}
        classifier_status = "fallback"

    payload = {
        "source": service,
        "entity_id": f"{service}.service",
        "signal_key": "service.health",
        "observed_at": utc_now(),
        "value": result,
        "value_kind": "object",
        "metadata": {
            "service": service,
            "health_url": url,
            "bridge": "ark-app-bridge",
        },
        "classifier_status": classifier_status,
        "raw_payload": result,
    }
    post_json(GENERIC_HOOK, payload)
    state.setdefault("health", {})[health_key] = now


def latest_jellyfin_log():
    candidates = glob.glob(JELLYFIN_LOG_GLOB)
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def parse_jellyfin_line(line):
    match = JELLYFIN_LINE_RE.match(line.strip())
    if not match:
        return None
    parts = match.groupdict()
    return {
        "NotificationType": "ServerLog",
        "Timestamp": parts["timestamp"],
        "ItemId": parts["component"].strip().lower().replace(" ", "."),
        "ItemType": "server",
        "Name": parts["component"].strip(),
        "Level": parts["level"],
        "Message": parts["message"].strip(),
        "Thread": parts["thread"].strip(),
        "ServerName": socket.gethostname(),
    }


def parse_unifi_line(line):
    match = UNIFI_LINE_RE.match(line.strip())
    if not match:
        return None
    parts = match.groupdict()
    return {
        "event_type": "server_log",
        "timestamp": parts["timestamp"],
        "entity_id": "unifi.server",
        "subsystem": parts["component"].strip().lower(),
        "severity": parts["level"].strip().lower(),
        "value": {
            "level": parts["level"].strip(),
            "message": parts["message"].strip(),
            "thread": parts["thread"].strip(),
        },
        "host": socket.gethostname(),
    }


def pump_log_file(state, source_key, file_path, parser, hook_path):
    if not os.path.exists(file_path):
        return

    file_state = state.setdefault("logs", {}).setdefault(source_key, {})
    cursor = int(file_state.get(file_path, 0))
    file_size = os.path.getsize(file_path)
    if cursor > file_size:
        cursor = 0

    emitted = 0
    with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
        handle.seek(cursor)
        while emitted < MAX_LINES_PER_POLL:
            line = handle.readline()
            if not line:
                break
            cursor = handle.tell()
            parsed = parser(line)
            if not parsed:
                continue
            post_json(hook_path, parsed)
            emitted += 1

    file_state[file_path] = cursor


def main():
    state = load_state()
    while True:
        for service_name, url in (
            ("homeassistant", HA_HEALTH_URL),
            ("jellyfin", JELLYFIN_HEALTH_URL),
            ("unifi", UNIFI_HEALTH_URL),
        ):
            try:
                emit_health(state, service_name, url)
            except Exception as exc:
                print(f"[bridge] {service_name} health emit failed: {exc}", flush=True)

        try:
            jellyfin_log = latest_jellyfin_log()
            if jellyfin_log:
                pump_log_file(state, "jellyfin", jellyfin_log, parse_jellyfin_line, JELLYFIN_HOOK)
        except Exception as exc:
            print(f"[bridge] jellyfin log pump failed: {exc}", flush=True)

        try:
            for log_file in UNIFI_LOG_FILES:
                pump_log_file(state, "unifi", log_file, parse_unifi_line, UNIFI_HOOK)
        except Exception as exc:
            print(f"[bridge] unifi log pump failed: {exc}", flush=True)

        save_state(state)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
