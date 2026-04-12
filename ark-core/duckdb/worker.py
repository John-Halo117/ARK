"""DuckDB worker — creates SSOT file and subscribes to NATS (replace with your pipeline)."""

import asyncio
import logging
import os

import duckdb
import nats

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/ark.duckdb")
NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")


def ensure_db(path: str | None = None) -> str:
    """Create database file and base table. Returns resolved path."""
    db = path or DB_PATH
    parent = os.path.dirname(db)
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = duckdb.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS ark_meta (k VARCHAR PRIMARY KEY, v VARCHAR)")
    con.close()
    return db


async def run() -> None:
    ensure_db()
    nc = await nats.connect(servers=[NATS_URL])
    try:
        logger.info("duckdb worker connected to NATS %s db %s", NATS_URL, DB_PATH)
        while True:
            await asyncio.sleep(3600)
    finally:
        await nc.drain()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
