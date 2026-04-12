"""Bridge Composio ↔ NATS — replace with real tool routing."""

import asyncio
import logging
import os

import nats

logger = logging.getLogger(__name__)

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")


def require_composio_key() -> str:
    key = os.environ.get("COMPOSIO_API_KEY", "").strip()
    if not key:
        msg = "COMPOSIO_API_KEY is not set or empty"
        raise RuntimeError(msg)
    return key


async def run() -> None:
    require_composio_key()
    nc = await nats.connect(servers=[NATS_URL])
    try:
        logger.info("composio_bridge connected %s", NATS_URL)
        while True:
            await asyncio.sleep(3600)
    finally:
        await nc.drain()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
