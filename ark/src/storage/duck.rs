use duckdb::{Connection, params};
use crate::types::LKS;
use crate::delta::compute::Delta;

pub struct DuckStore {
    pub conn: Connection,
}

impl DuckStore {
    pub fn new(path: &str) -> Result<Self, duckdb::Error> {
        let conn = Connection::open(path)?;

        conn.execute_batch("
            CREATE TABLE IF NOT EXISTS lks (
                ts BIGINT,
                qts FLOAT,
                dsi FLOAT,
                dss FLOAT,
                phase TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_lks_ts ON lks(ts);

            CREATE TABLE IF NOT EXISTS delta (
                ts BIGINT,
                raw FLOAT,
                pct FLOAT,
                q INTEGER,
                vec TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_delta_ts ON delta(ts);
        ")?;

        Ok(Self { conn })
    }

    pub fn insert_lks(&self, ts: u64, lks: &LKS) -> Result<usize, duckdb::Error> {
        self.conn.execute(
            "INSERT INTO lks VALUES (?1, ?2, ?3, ?4, ?5)",
            params![ts, lks.qts, lks.dsi, lks.dss, lks.phase],
        )
    }

    pub fn insert_delta(&self, ts: u64, d: &Delta) -> Result<usize, duckdb::Error> {
        self.conn.execute(
            "INSERT INTO delta VALUES (?1, ?2, ?3, ?4, ?5)",
            params![ts, d.raw, d.pct, d.q, d.vec],
        )
    }
}
