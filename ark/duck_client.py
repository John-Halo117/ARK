"""
DuckDB client for Python agents - query/write state, metrics, events
Hardened: parameterized queries, input validation, size limits.
"""

import json
import logging
from typing import List, Dict, Any, Optional
from ark.event_schema import ArkEvent, LKS
from ark.security import clamp_limit, sanitize_string

logger = logging.getLogger("ARK-DuckClient")


class DuckClient:
    """Interface to DuckDB for Python side"""
    
    def __init__(self, db_path: str = "/data/ark.duckdb"):
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("duckdb package is required for DuckClient") from exc
        self.conn = duckdb.connect(db_path)
        self._init_tables()
    
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
        lks_json = event.lks.to_dict() if event.lks else None
        
        self.conn.execute("""
            INSERT INTO events 
            (event_id, event_type, source, timestamp, payload, lks, decision, delta, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            event.event_id,
            event.event_type.value,
            event.source.value,
            event.timestamp,
            json.dumps(event.payload, default=str),
            json.dumps(lks_json, default=str) if lks_json is not None else None,
            event.decision,
            json.dumps(event.delta, default=str) if event.delta is not None else None,
            json.dumps(event.tags or {}, default=str)
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
        
        columns = ["source", "qts", "dsi", "dss", "phase", "timestamp", "created_at"]
        return [_row_to_dict(columns, row) for row in result]
    
    def get_state(self, key: str) -> Optional[Dict[str, Any]]:
        """Get state value"""
        result = self.conn.execute(
            "SELECT value FROM state WHERE key = ?",
            [key]
        ).fetchone()
        return _decode_json_value(result[0]) if result else None
    
    def set_state(self, key: str, value: Dict[str, Any]):
        """Set state value (upsert) — fixed ON CONFLICT syntax"""
        key = sanitize_string(key, 256)
        self.conn.execute("""
            INSERT INTO state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """, [key, json.dumps(value, default=str)])
    
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
        
        cursor = self.conn.execute(query, params)
        columns = [column[0] for column in cursor.description]
        return [_row_to_dict(columns, row) for row in cursor.fetchall()]
    
    def get_mesh_status(self) -> Dict[str, Any]:
        """Query system status"""
        event_count = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        lks_count = self.conn.execute("SELECT COUNT(*) FROM lks_metrics").fetchone()[0]
        
        return {
            "event_count": event_count,
            "lks_count": lks_count,
            "db_path": _database_name(self.conn)
        }


def _row_to_dict(columns: list[str], row: Any) -> Dict[str, Any]:
    return {column: _decode_json_value(value) for column, value in zip(columns, row)}


def _decode_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{\"0123456789-tnf":
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _database_name(conn: Any) -> str:
    get_database_name = getattr(conn, "get_database_name", None)
    if callable(get_database_name):
        return str(get_database_name())
    return "unknown"
