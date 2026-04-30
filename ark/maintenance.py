"""
ARK Maintenance Module — health probes, connection resilience, graceful
shutdown coordination, periodic cleanup, and structured diagnostics.
"""

import asyncio
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

try:
    import nats
except ImportError:  # pragma: no cover - exercised by import-only environments
    nats = None

logger = logging.getLogger("ARK-Maintenance")

# ---------------------------------------------------------------------------
# Graceful shutdown coordinator
# ---------------------------------------------------------------------------


class ShutdownCoordinator:
    """Coordinates graceful shutdown across async tasks.

    Usage::

        coord = ShutdownCoordinator()
        coord.install_signal_handlers()

        async def worker():
            while not coord.is_shutting_down:
                await do_work()
            await coord.wait_for_shutdown()

        async def main():
            await asyncio.gather(worker(), coord.shutdown_on_signal())
    """

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout
        self._shutdown_event = asyncio.Event()
        self._callbacks: List[Callable[[], Coroutine]] = []
        self._started_at = time.monotonic()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_event.is_set()

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def request_shutdown(self) -> None:
        """Signal all waiters that shutdown has been requested."""
        if not self._shutdown_event.is_set():
            logger.info("Shutdown requested")
            self._shutdown_event.set()

    def on_shutdown(self, callback: Callable[[], Coroutine]) -> None:
        """Register an async cleanup callback."""
        self._callbacks.append(callback)

    async def wait_for_shutdown(self) -> None:
        """Block until shutdown is requested."""
        await self._shutdown_event.wait()

    async def run_cleanup(self) -> None:
        """Run all registered cleanup callbacks with a timeout."""
        logger.info("Running %d shutdown callbacks (timeout=%ss)", len(self._callbacks), self._timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*(cb() for cb in self._callbacks), return_exceptions=True),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Shutdown cleanup timed out after %ss", self._timeout)
        logger.info("Shutdown cleanup complete")

    def install_signal_handlers(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Install SIGINT/SIGTERM handlers on the running event loop."""
        loop = loop or asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_shutdown)
            except NotImplementedError:
                pass  # Windows


# ---------------------------------------------------------------------------
# NATS connection with auto-reconnect
# ---------------------------------------------------------------------------


class ResilientNATSConnection:
    """Wraps a NATS connection with exponential-backoff reconnect and health
    probing.

    Args:
        url: NATS server URL
        max_reconnect_delay: ceiling for backoff (seconds)
        connect_timeout: per-attempt timeout (seconds)
    """

    def __init__(
        self,
        url: str = "nats://nats:4222",
        max_reconnect_delay: float = 60.0,
        connect_timeout: float = 10.0,
        max_attempts: int = 10,
    ):
        self.url = url
        self._max_delay = max_reconnect_delay
        self._connect_timeout = connect_timeout
        self._max_attempts = max(1, min(max_attempts, 100))
        self.nc: Optional[Any] = None
        self.js = None
        self._attempt = 0

    @property
    def is_connected(self) -> bool:
        return self.nc is not None and self.nc.is_connected

    async def connect(self) -> Any:
        """Connect (or reconnect) with exponential backoff."""
        if nats is None:
            raise RuntimeError("nats package is not installed")
        for _ in range(self._max_attempts):
            try:
                self._attempt += 1
                self.nc = await nats.connect(
                    self.url,
                    max_reconnect_attempts=5,
                    reconnect_time_wait=2,
                    connect_timeout=self._connect_timeout,
                    error_cb=self._on_error,
                    disconnected_cb=self._on_disconnect,
                    reconnected_cb=self._on_reconnect,
                    closed_cb=self._on_closed,
                )
                self.js = self.nc.jetstream()
                self._attempt = 0
                logger.info("Connected to NATS at %s", self.url)
                return self.nc
            except Exception as exc:
                delay = min(2 ** self._attempt, self._max_delay)
                logger.warning(
                    "NATS connect attempt %d failed (%s); retrying in %ss",
                    self._attempt,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        raise RuntimeError(f"NATS unavailable after {self._max_attempts} attempts")

    async def close(self) -> None:
        if self.nc:
            try:
                await self.nc.drain()
            except Exception:
                pass
            try:
                await self.nc.close()
            except Exception:
                pass
            self.nc = None
            self.js = None

    # --- internal callbacks ---------------------------------------------------

    async def _on_error(self, exc: Exception) -> None:
        logger.error("NATS error: %s", exc)

    async def _on_disconnect(self) -> None:
        logger.warning("NATS disconnected")

    async def _on_reconnect(self) -> None:
        logger.info("NATS reconnected")

    async def _on_closed(self) -> None:
        logger.info("NATS connection closed")


# ---------------------------------------------------------------------------
# Health check registry
# ---------------------------------------------------------------------------


class HealthCheck:
    """Collects named health probes and exposes a single ``check()`` method
    that returns an aggregate status.

    Usage::

        hc = HealthCheck("my-service")
        hc.register("nats", lambda: nats_conn.is_connected)
        hc.register("db", lambda: db_client.conn is not None)

        status = hc.check()   # {"healthy": True, "checks": {...}}
    """

    def __init__(self, service_name: str):
        self.service_name = service_name
        self._probes: Dict[str, Callable[[], bool]] = {}
        self._started_at = datetime.now(timezone.utc)

    def register(self, name: str, probe: Callable[[], bool]) -> None:
        self._probes[name] = probe

    def check(self) -> Dict[str, Any]:
        results: Dict[str, bool] = {}
        for name, probe in self._probes.items():
            try:
                results[name] = bool(probe())
            except Exception:
                results[name] = False

        all_healthy = all(results.values()) if results else True
        return {
            "service": self.service_name,
            "healthy": all_healthy,
            "checks": results,
            "uptime_seconds": (datetime.now(timezone.utc) - self._started_at).total_seconds(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Periodic cleanup runner
# ---------------------------------------------------------------------------


class PeriodicTask:
    """Run an async callable on a fixed interval, with jitter and error
    tolerance.

    Args:
        name: human-readable label (for logging)
        interval: seconds between executions
        func: async callable to run
        max_failures: consecutive failures before the task self-disables
    """

    def __init__(
        self,
        name: str,
        interval: float,
        func: Callable[[], Coroutine],
        max_failures: int = 10,
        max_runs: int = 1_000_000,
    ):
        self.name = name
        self.interval = interval
        self.func = func
        self.max_failures = max_failures
        self.max_runs = max(1, min(max_runs, 1_000_000))
        self._consecutive_failures = 0
        self._total_runs = 0
        self._disabled = False

    @property
    def is_disabled(self) -> bool:
        return self._disabled

    async def run_forever(self, shutdown: Optional[ShutdownCoordinator] = None) -> None:
        """Loop until disabled or shutdown is requested."""
        logger.info("Periodic task %r started (interval=%ss)", self.name, self.interval)
        for _ in range(self.max_runs):
            if self._disabled:
                break
            if shutdown and shutdown.is_shutting_down:
                break
            try:
                await asyncio.sleep(self.interval)
                await self.func()
                self._total_runs += 1
                self._consecutive_failures = 0
            except asyncio.CancelledError:
                break
            except Exception:
                self._consecutive_failures += 1
                logger.exception(
                    "Periodic task %r failed (%d/%d)",
                    self.name,
                    self._consecutive_failures,
                    self.max_failures,
                )
                if self._consecutive_failures >= self.max_failures:
                    logger.error("Periodic task %r disabled after %d failures", self.name, self.max_failures)
                    self._disabled = True
        if self._total_runs >= self.max_runs:
            self._disabled = True

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "total_runs": self._total_runs,
            "consecutive_failures": self._consecutive_failures,
            "disabled": self._disabled,
        }


# ---------------------------------------------------------------------------
# Stale-data cleaner for DuckDB
# ---------------------------------------------------------------------------


async def cleanup_old_events(db_conn: Any, days: int = 30) -> int:
    """Delete events older than *days* from the events table.

    Returns the number of deleted rows.
    """
    import time as _time

    cutoff = int(_time.time()) - (days * 86_400)
    try:
        before = db_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        db_conn.execute("DELETE FROM events WHERE timestamp < ?", [cutoff])
        after = db_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        deleted = before - after
        if deleted:
            logger.info("Cleaned up %d old events (cutoff=%d days)", deleted, days)
        return deleted
    except Exception:
        logger.exception("Event cleanup failed")
        return 0


async def cleanup_old_metrics(db_conn: Any, days: int = 7) -> int:
    """Delete LKS metrics older than *days*."""
    import time as _time

    cutoff = int(_time.time()) - (days * 86_400)
    try:
        before = db_conn.execute("SELECT COUNT(*) FROM lks_metrics").fetchone()[0]
        db_conn.execute("DELETE FROM lks_metrics WHERE timestamp < ?", [cutoff])
        after = db_conn.execute("SELECT COUNT(*) FROM lks_metrics").fetchone()[0]
        deleted = before - after
        if deleted:
            logger.info("Cleaned up %d old LKS metrics (cutoff=%d days)", deleted, days)
        return deleted
    except Exception:
        logger.exception("Metric cleanup failed")
        return 0


async def vacuum_db(db_conn: Any) -> None:
    """Reclaim space after bulk deletes."""
    try:
        db_conn.execute("CHECKPOINT")
        logger.info("DuckDB checkpoint complete")
    except Exception:
        logger.exception("DuckDB checkpoint failed")


# ---------------------------------------------------------------------------
# Connection watchdog
# ---------------------------------------------------------------------------


class ConnectionWatchdog:
    """Monitors a ``ResilientNATSConnection`` and triggers reconnect on
    failure.

    Usage::

        wd = ConnectionWatchdog(nats_conn, interval=10)
        asyncio.create_task(wd.run())
    """

    def __init__(self, conn: ResilientNATSConnection, interval: float = 10.0, max_checks: int = 1_000_000):
        self._conn = conn
        self._interval = interval
        self._max_checks = max(1, min(max_checks, 1_000_000))
        self._reconnect_count = 0

    async def run(self, shutdown: Optional[ShutdownCoordinator] = None) -> None:
        for _ in range(self._max_checks):
            if shutdown and shutdown.is_shutting_down:
                break
            await asyncio.sleep(self._interval)
            if not self._conn.is_connected:
                self._reconnect_count += 1
                logger.warning(
                    "NATS watchdog: connection lost, reconnecting (#%d)",
                    self._reconnect_count,
                )
                try:
                    await self._conn.connect()
                except Exception:
                    logger.exception("NATS watchdog reconnect failed")

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count
