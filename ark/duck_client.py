"""
DuckDB client for Python agents - query/write state, metrics, events
Hardened: parameterized queries, input validation, size limits.
"""

import duckdb
import json
import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from ark.event_schema import ArkEvent, LKS
from ark.security import clamp_limit, sanitize_string

logger = logging.getLogger("ARK-DuckClient")


class DuckClient:
    """Interface to DuckDB for Python side"""
    
    def __init__(self, db_path: str = "/data/ark.duckdb"):
        if db_path != ":memory:":
            db_path = self._prepare_db_path(db_path)
        self.conn = duckdb.connect(db_path)
        self._init_tables()

    def _prepare_db_path(self, db_path: str) -> str:
        """Return a writable database path.

        Runtime: O(1). Memory: O(1). Failure: propagates non-default path errors.
        """
        path = Path(db_path).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return str(path)
        except OSError:
            if str(path) != "/data/ark.duckdb":
                raise
            fallback = Path(tempfile.gettempdir()) / "ark" / "ark.duckdb"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            logger.warning("Default DuckDB path unavailable; using local fallback %s", fallback)
            return str(fallback)
    
    def _init_tables(self):
        """Create tables if not exist"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id VARCHAR PRIMARY KEY,
                event_type VARCHAR,
                source VARCHAR,
                timestamp BIGINT,
                payload JSON,
                lks JSON,
                decision VARCHAR,
                delta JSON,
                tags JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_lks_id START 1")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS lks_metrics (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_lks_id'),
                source VARCHAR,
                qts FLOAT,
                dsi FLOAT,
                dss FLOAT,
                phase VARCHAR,
                timestamp BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.execute("CREATE SEQUENCE IF NOT EXISTS seq_delta_id START 1")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS deltas (
                id INTEGER PRIMARY KEY DEFAULT nextval('seq_delta_id'),
                source VARCHAR,
                raw FLOAT,
                pct FLOAT,
                q INTEGER,
                vec VARCHAR,
                timestamp BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS state (
                key VARCHAR PRIMARY KEY,
                value JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    
    def insert_event(self, event: ArkEvent):
        """Store event"""
        lks_json = json.dumps(event.lks.to_dict(), default=str) if event.lks else None
        
        self.conn.execute("""
            INSERT INTO events 
            (event_id, event_type, source, timestamp, payload, lks, decision, delta, tags)
            VALUES (?, ?, ?, ?, ?::JSON, ?::JSON, ?, ?::JSON, ?::JSON)
        """, [
            event.event_id,
            event.event_type.value,
            event.source.value,
            event.timestamp,
            json.dumps(event.payload, default=str),
            lks_json,
            event.decision,
            json.dumps(event.delta, default=str) if event.delta is not None else None,
            json.dumps(event.tags or {}, default=str),
        ])
    
    def insert_lks(self, source: str, lks: LKS, timestamp: int):
        """Store LKS metrics"""
        self.conn.execute("""
            INSERT INTO lks_metrics (source, qts, dsi, dss, phase, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [source, lks.qts, lks.dsi, lks.dss, lks.phase, timestamp])
    
    def insert_delta(self, source: str, raw: float, pct: float, q: int, vec: str, timestamp: int):
        """Store delta"""
        self.conn.execute("""
            INSERT INTO deltas (source, raw, pct, q, vec, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [source, raw, pct, q, vec, timestamp])
    
    def get_latest_lks(self, source: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Query latest LKS for source (parameterized limit)"""
        safe_limit = clamp_limit(limit, default=10, ceiling=1000)
        source = sanitize_string(source, 128)
        result = self.conn.execute(
            "SELECT source, qts, dsi, dss, phase, timestamp, created_at "
            "FROM lks_metrics WHERE source = ? ORDER BY timestamp DESC LIMIT ?",
            [source, safe_limit],
        ).fetchall()
        
        return [dict(r) for r in result]
    
    def get_state(self, key: str) -> Optional[Dict[str, Any]]:
        """Get state value"""
        result = self.conn.execute(
            "SELECT value FROM state WHERE key = ?",
            [key]
        ).fetchone()
        if not result:
            return None
        value = result[0]
        if isinstance(value, str):
            return json.loads(value)
        return value
    
    def set_state(self, key: str, value: Dict[str, Any]):
        """Set state value with deterministic bounded upsert."""
        key = sanitize_string(key, 256)
        payload = json.dumps(value, default=str)
        updated = self.conn.execute(
            "UPDATE state SET value = ?::JSON, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
            [payload, key],
        ).rowcount
        exists = self.conn.execute("SELECT COUNT(*) FROM state WHERE key = ?", [key]).fetchone()[0]
        if updated == 0 or exists == 0:
            self.conn.execute(
                "INSERT INTO state (key, value, updated_at) VALUES (?, ?::JSON, CURRENT_TIMESTAMP)",
                [key, payload],
            )
    
    def query_events(self, source: Optional[str] = None, event_type: Optional[str] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
        """Query events with filters (parameterized limit, no f-string injection)"""
        safe_limit = clamp_limit(limit)
        query = "SELECT * FROM events WHERE 1=1"
        params: list = []
        
        if source:
            query += " AND source = ?"
            params.append(sanitize_string(source, 128))
        if event_type:
            query += " AND event_type = ?"
            params.append(sanitize_string(event_type, 64))
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(safe_limit)
        
        result = self.conn.execute(query, params).fetchall()
        columns = [column[0] for column in self.conn.description]
        return [dict(zip(columns, r)) for r in result]

    def query_events_page(
        self,
        source: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Query a bounded event page.

        Input schema:
            source: optional string, max 128 chars.
            event_type: optional string, max 64 chars.
            limit: integer clamped to [1, 200].
            cursor: optional Unix timestamp; returns records older than cursor.
        Output schema:
            {"count": int, "events": list[dict], "next_cursor": int | None}
        Runtime: O(limit). Memory: O(limit). Failure: raises DuckDB/validation errors.
        """
        safe_limit = clamp_limit(limit, default=50, ceiling=200)
        query = "SELECT * FROM events WHERE 1=1"
        params: list = []

        if source:
            query += " AND source = ?"
            params.append(sanitize_string(source, 128))
        if event_type:
            query += " AND event_type = ?"
            params.append(sanitize_string(event_type, 64))
        if cursor is not None:
            query += " AND timestamp < ?"
            params.append(int(cursor))

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(safe_limit)

        result = self.conn.execute(query, params).fetchall()
        columns = [column[0] for column in self.conn.description]
        events = [dict(zip(columns, row)) for row in result]
        next_cursor = None
        if len(events) == safe_limit and events[-1].get("timestamp") is not None:
            next_cursor = int(events[-1]["timestamp"])
        return {"count": len(events), "events": events, "next_cursor": next_cursor}
    
    def get_mesh_status(self) -> Dict[str, Any]:
        """Query system status"""
        event_count = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        lks_count = self.conn.execute("SELECT COUNT(*) FROM lks_metrics").fetchone()[0]
        
        return {
            "event_count": event_count,
            "lks_count": lks_count,
            "db_path": self.conn.get_database_name()
        }
