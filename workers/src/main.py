"""Entrypoint del proceso de workers.

En esta fase 1 sólo arranca un loop vacío. Las colas BullMQ y los cron jobs
se conectarán en la fase 2.
"""

from __future__ import annotations

import asyncio
import logging
import signal

import structlog

logger = structlog.get_logger(__name__)


async def run() -> None:
    logging.basicConfig(level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )
    logger.info("workers_started")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    logger.info("workers_stopping")


if __name__ == "__main__":
    asyncio.run(run())
