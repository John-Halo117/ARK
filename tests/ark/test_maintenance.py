"""Tests for ark.maintenance module — health checks, shutdown coordinator,
periodic tasks, resilient NATS connection, cleanup helpers."""

import asyncio
import pytest
from unittest.mock import MagicMock

from ark.maintenance import (
    ShutdownCoordinator,
    ResilientNATSConnection,
    HealthCheck,
    PeriodicTask,
    ConnectionWatchdog,
    cleanup_old_events,
    cleanup_old_metrics,
    vacuum_db,
)


# ---------------------------------------------------------------------------
# ShutdownCoordinator
# ---------------------------------------------------------------------------


class TestShutdownCoordinator:
    def test_initial_state(self):
        sc = ShutdownCoordinator()
        assert sc.is_shutting_down is False
        assert sc.uptime_seconds >= 0

    def test_request_shutdown(self):
        sc = ShutdownCoordinator()
        sc.request_shutdown()
        assert sc.is_shutting_down is True

    def test_double_request_is_safe(self):
        sc = ShutdownCoordinator()
        sc.request_shutdown()
        sc.request_shutdown()
        assert sc.is_shutting_down is True

    @pytest.mark.asyncio
    async def test_wait_for_shutdown(self):
        sc = ShutdownCoordinator()
        # Schedule shutdown after a tiny delay
        async def trigger():
            await asyncio.sleep(0.01)
            sc.request_shutdown()
        asyncio.create_task(trigger())
        await sc.wait_for_shutdown()
        assert sc.is_shutting_down is True

    @pytest.mark.asyncio
    async def test_run_cleanup_calls_callbacks(self):
        sc = ShutdownCoordinator(timeout=5)
        called = []
        async def cb1():
            called.append("cb1")
        async def cb2():
            called.append("cb2")
        sc.on_shutdown(cb1)
        sc.on_shutdown(cb2)
        await sc.run_cleanup()
        assert "cb1" in called
        assert "cb2" in called

    @pytest.mark.asyncio
    async def test_run_cleanup_handles_timeout(self):
        sc = ShutdownCoordinator(timeout=0.01)
        async def slow_cb():
            await asyncio.sleep(10)
        sc.on_shutdown(slow_cb)
        # Should not hang
        await sc.run_cleanup()


# ---------------------------------------------------------------------------
# HealthCheck
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_no_probes_is_healthy(self):
        hc = HealthCheck("test-service")
        status = hc.check()
        assert status["healthy"] is True
        assert status["service"] == "test-service"

    def test_all_passing(self):
        hc = HealthCheck("svc")
        hc.register("a", lambda: True)
        hc.register("b", lambda: True)
        status = hc.check()
        assert status["healthy"] is True
        assert status["checks"]["a"] is True

    def test_one_failing(self):
        hc = HealthCheck("svc")
        hc.register("ok", lambda: True)
        hc.register("bad", lambda: False)
        status = hc.check()
        assert status["healthy"] is False
        assert status["checks"]["bad"] is False

    def test_exception_counts_as_unhealthy(self):
        hc = HealthCheck("svc")
        def explode():
            raise RuntimeError("boom")
        hc.register("explode", explode)
        status = hc.check()
        assert status["healthy"] is False
        assert status["checks"]["explode"] is False

    def test_uptime_in_output(self):
        hc = HealthCheck("svc")
        status = hc.check()
        assert "uptime_seconds" in status
        assert status["uptime_seconds"] >= 0

    def test_timestamp_in_output(self):
        hc = HealthCheck("svc")
        status = hc.check()
        assert "timestamp" in status


# ---------------------------------------------------------------------------
# PeriodicTask
# ---------------------------------------------------------------------------


class TestPeriodicTask:
    @pytest.mark.asyncio
    async def test_runs_and_counts(self):
        counter = {"n": 0}
        async def inc():
            counter["n"] += 1
        pt = PeriodicTask("counter", interval=0.01, func=inc)
        # Run briefly then cancel
        task = asyncio.create_task(pt.run_forever())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert counter["n"] >= 1
        assert pt._total_runs >= 1

    @pytest.mark.asyncio
    async def test_disables_after_max_failures(self):
        async def fail():
            raise RuntimeError("always fails")
        pt = PeriodicTask("fail", interval=0.01, func=fail, max_failures=3)
        task = asyncio.create_task(pt.run_forever())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert pt.is_disabled is True

    def test_stats(self):
        async def noop():
            pass
        pt = PeriodicTask("noop", interval=1, func=noop)
        stats = pt.stats()
        assert stats["name"] == "noop"
        assert stats["total_runs"] == 0
        assert stats["disabled"] is False

    @pytest.mark.asyncio
    async def test_respects_shutdown(self):
        sc = ShutdownCoordinator()
        counter = {"n": 0}
        async def inc():
            counter["n"] += 1
        pt = PeriodicTask("counter", interval=0.01, func=inc)
        sc.request_shutdown()
        await pt.run_forever(shutdown=sc)
        # Should exit immediately without running
        assert counter["n"] == 0


# ---------------------------------------------------------------------------
# ResilientNATSConnection
# ---------------------------------------------------------------------------


class TestResilientNATSConnection:
    def test_initial_state(self):
        conn = ResilientNATSConnection("nats://test:4222")
        assert conn.is_connected is False
        assert conn.nc is None

    @pytest.mark.asyncio
    async def test_close_when_not_connected(self):
        conn = ResilientNATSConnection()
        await conn.close()  # Should not raise


# ---------------------------------------------------------------------------
# ConnectionWatchdog
# ---------------------------------------------------------------------------


class TestConnectionWatchdog:
    def test_initial_reconnect_count(self):
        conn = ResilientNATSConnection()
        wd = ConnectionWatchdog(conn, interval=1)
        assert wd.reconnect_count == 0


# ---------------------------------------------------------------------------
# DB cleanup helpers
# ---------------------------------------------------------------------------


class TestCleanupOldEvents:
    @pytest.mark.asyncio
    async def test_cleanup_deletes_old(self):
        mock_conn = MagicMock()
        # Before: 100 events, After: 90 events
        mock_conn.execute.return_value.fetchone.side_effect = [(100,), (90,)]
        deleted = await cleanup_old_events(mock_conn, days=30)
        assert deleted == 10

    @pytest.mark.asyncio
    async def test_cleanup_handles_error(self):
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("db error")
        deleted = await cleanup_old_events(mock_conn, days=30)
        assert deleted == 0


class TestCleanupOldMetrics:
    @pytest.mark.asyncio
    async def test_cleanup_deletes_old(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.side_effect = [(50,), (40,)]
        deleted = await cleanup_old_metrics(mock_conn, days=7)
        assert deleted == 10

    @pytest.mark.asyncio
    async def test_cleanup_handles_error(self):
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("db error")
        deleted = await cleanup_old_metrics(mock_conn, days=7)
        assert deleted == 0


class TestVacuumDb:
    @pytest.mark.asyncio
    async def test_vacuum_calls_checkpoint(self):
        mock_conn = MagicMock()
        await vacuum_db(mock_conn)
        mock_conn.execute.assert_called_once_with("CHECKPOINT")

    @pytest.mark.asyncio
    async def test_vacuum_handles_error(self):
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("db error")
        await vacuum_db(mock_conn)  # Should not raise
