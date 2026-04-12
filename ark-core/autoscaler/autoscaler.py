"""Dynamic service spawning — replace with real scaling logic."""

import asyncio
import logging
import os
from typing import Any

import docker
import nats

logger = logging.getLogger(__name__)

NATS_URL = os.environ.get("NATS_URL", "nats://localhost:4222")


def check_docker(client: Any = None) -> None:
    """Verify Docker daemon is reachable."""
    c = client or docker.from_env()
    c.ping()


async def run() -> None:
    check_docker()
    nc = await nats.connect(servers=[NATS_URL])
    try:
        logger.info("autoscaler connected; docker ok; NATS %s", NATS_URL)
        while True:
            await asyncio.sleep(3600)
    finally:
        await nc.drain()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
