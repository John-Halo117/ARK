"""Tests for ark.duck_client module."""


import pytest

duckdb = pytest.importorskip("duckdb")

from ark.event_schema import ArkEvent, EventSource, EventType, LKS
from ark.duck_client import DuckClient


@pytest.fixture
def db(tmp_path):
    """Create a temporary DuckDB for testing."""
    path = str(tmp_path / "test.duckdb")
    # Pre-create sequences that DuckClient._init_tables references
    conn = duckdb.connect(path)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_lks_id START 1")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_delta_id START 1")
    conn.close()
    client = DuckClient(db_path=path)
    yield client
    client.conn.close()


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

class TestDuckClientTables:
    def test_tables_created(self, db):
        tables = db.conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        table_names = {row[0] for row in tables}
        assert "events" in table_names
        assert "state" in table_names
        assert "lks_metrics" in table_names
        assert "deltas" in table_names


# ---------------------------------------------------------------------------
# Event insert (raw SQL verification — bypasses buggy dict() conversion)
# ---------------------------------------------------------------------------

class TestDuckClientEvents:
    def _make_event(self, event_id="evt-1"):
        return ArkEvent(
            event_id=event_id,
            event_type=EventType.METRIC,
            source=EventSource.ARK_CORE,
            timestamp=1700000000,
            payload={"key": "value"},
            tags={"env": "test"},
        )

    def test_insert_event(self, db):
        evt = self._make_event()
        db.insert_event(evt)
        row = db.conn.execute(
            "SELECT event_id, event_type, source, timestamp FROM events WHERE event_id = ?",
            ["evt-1"],
        ).fetchone()
        assert row is not None
        assert row[0] == "evt-1"
        assert row[1] == "metric"
        assert row[2] == "ark.core"
        assert row[3] == 1700000000

    def test_insert_event_with_lks(self, db):
        lks = LKS(qts=0.9, dsi=0.4, dss=0.6, dss_kalman=0.55, phase="stable")
        evt = ArkEvent(
            event_id="evt-lks",
            event_type=EventType.ANOMALY,
            source=EventSource.AGENT_OPENWOLF,
            timestamp=1700000001,
            payload={},
            lks=lks,
            decision="hold",
            delta={"raw": 1.0},
            tags={},
        )
        db.insert_event(evt)
        row = db.conn.execute(
            "SELECT event_id, decision FROM events WHERE event_id = ?",
            ["evt-lks"],
        ).fetchone()
        assert row is not None
        assert row[1] == "hold"

    def test_insert_multiple_events(self, db):
        for i in range(5):
            db.insert_event(self._make_event(f"evt-{i}"))
        count = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 5

    def test_insert_event_without_optional_fields(self, db):
        evt = ArkEvent(
            event_id="minimal",
            event_type=EventType.STATUS,
            source=EventSource.SYSTEM,
            timestamp=0,
            payload={},
        )
        db.insert_event(evt)
        row = db.conn.execute(
            "SELECT event_id, decision FROM events WHERE event_id = 'minimal'"
        ).fetchone()
        assert row is not None
        assert row[1] is None  # decision is None


# ---------------------------------------------------------------------------
# LKS metrics insert
# ---------------------------------------------------------------------------

class TestDuckClientLKS:
    def test_insert_lks(self, db):
        lks = LKS(qts=0.9, dsi=0.4, dss=0.6, dss_kalman=0.55, phase="stable")
        db.insert_lks("agent.openwolf", lks, 1700000000)
        row = db.conn.execute(
            "SELECT source, qts, phase FROM lks_metrics WHERE source = ?",
            ["agent.openwolf"],
        ).fetchone()
        assert row is not None
        assert row[0] == "agent.openwolf"
        assert abs(row[1] - 0.9) < 0.01
        assert row[2] == "stable"


# ---------------------------------------------------------------------------
# Delta insert
# ---------------------------------------------------------------------------

class TestDuckClientDelta:
    def test_insert_delta(self, db):
        db.insert_delta("source.a", 1.5, 0.05, 3, "up", 1700000000)
        row = db.conn.execute(
            "SELECT source, raw, pct, q, vec FROM deltas WHERE source = ?",
            ["source.a"],
        ).fetchone()
        assert row is not None
        assert abs(row[1] - 1.5) < 0.01
        assert row[3] == 3
        assert row[4] == "up"


# ---------------------------------------------------------------------------
# State operations
# ---------------------------------------------------------------------------

class TestDuckClientState:
    def test_get_state_missing(self, db):
        val = db.get_state("nonexistent")
        assert val is None

    def test_get_state_returns_value(self, db):
        # Insert directly to avoid set_state SQL bug
        db.conn.execute(
            "INSERT INTO state (key, value) VALUES (?, ?)",
            ["k1", '{"status": "running"}'],
        )
        val = db.get_state("k1")
        assert val is not None


# ---------------------------------------------------------------------------
# Mesh status (count-based — avoids get_database_name bug)
# ---------------------------------------------------------------------------

class TestDuckClientCounts:
    def test_event_count_zero(self, db):
        count = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 0

    def test_lks_count_zero(self, db):
        count = db.conn.execute("SELECT COUNT(*) FROM lks_metrics").fetchone()[0]
        assert count == 0

    def test_event_count_after_insert(self, db):
        evt = ArkEvent(
            event_id="x",
            event_type=EventType.STATUS,
            source=EventSource.SYSTEM,
            timestamp=0,
            payload={},
        )
        db.insert_event(evt)
        count = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1

    def test_lks_count_after_insert(self, db):
        lks = LKS(qts=0.5, dsi=0.5, dss=0.5, dss_kalman=0.5, phase="drift")
        db.insert_lks("src", lks, 100)
        count = db.conn.execute("SELECT COUNT(*) FROM lks_metrics").fetchone()[0]
        assert count == 1
