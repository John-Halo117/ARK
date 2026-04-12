"""AAR plugin host — replace with your agent runtime."""

import asyncio
import logging
import os

import duckdb
import nats

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/ark.duckdb")
NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")


def verify_db_read(path: str | None = None) -> bool:
    """Return True if DuckDB file exists and is readable."""
    db = path or DB_PATH
    if not os.path.exists(db):
        return False
    con = duckdb.connect(db, read_only=True)
    try:
        con.execute("SELECT 1")
    finally:
        con.close()
    return True


async def run() -> None:
    if verify_db_read():
        logger.info("AAR: DuckDB readable at %s", DB_PATH)
    else:
        logger.warning("AAR: waiting for DuckDB at %s", DB_PATH)

    nc = await nats.connect(servers=[NATS_URL])
    try:
        logger.info("aar connected %s", NATS_URL)
        while True:
            await asyncio.sleep(3600)
    finally:
        await nc.drain()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
