"""Capability graph registry over NATS — replace with real registration logic."""

import asyncio
import logging
import os

import nats

logger = logging.getLogger(__name__)

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")


async def run() -> None:
    nc = await nats.connect(servers=[NATS_URL])
    try:
        logger.info("mesh-registry connected %s", NATS_URL)
        while True:
            await asyncio.sleep(3600)
    finally:
        await nc.drain()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
