use duckdb::{Connection, params};
use crate::types::LKS;
use crate::delta::compute::Delta;

pub struct DuckStore {
    pub conn: Connection,
}

impl DuckStore {
    pub fn new(path: &str) -> Self {
        let conn = Connection::open(path).unwrap();

        conn.execute_batch("
            CREATE TABLE IF NOT EXISTS lks (
                ts BIGINT,
                qts FLOAT,
                dsi FLOAT,
                dss FLOAT,
                phase TEXT
            );

            CREATE TABLE IF NOT EXISTS delta (
                ts BIGINT,
                raw FLOAT,
                pct FLOAT,
                q INTEGER,
                vec TEXT
            );
        ").unwrap();

        Self { conn }
    }

    pub fn insert_lks(&self, ts: u64, lks: &LKS) {
        self.conn.execute(
            "INSERT INTO lks VALUES (?1, ?2, ?3, ?4, ?5)",
            params![ts, lks.qts, lks.dsi, lks.dss, lks.phase],
        ).unwrap();
    }

    pub fn insert_delta(&self, ts: u64, d: &Delta) {
        self.conn.execute(
            "INSERT INTO delta VALUES (?1, ?2, ?3, ?4, ?5)",
            params![ts, d.raw, d.pct, d.q, d.vec],
        ).unwrap();
    }
}
