"""Runs the ai worker: one loop reading backend jobs. Start with `python -m src.worker`;
Ctrl+C (or SIGTERM) stops it after the current job."""

import asyncio
import logging
import signal

from redis.asyncio import Redis

from src.config import get_settings
from src.streams import REQUEST_HANDLERS, AiRequestConsumer, stop_task

logger = logging.getLogger(__name__)


async def main():
    settings = get_settings()
    redis: Redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    consumer = AiRequestConsumer(redis, REQUEST_HANDLERS, settings)
    task: asyncio.Task = asyncio.create_task(consumer.run(), name="ai-request-consumer")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            # windows: no loop signal handlers; Ctrl+C raises KeyboardInterrupt instead
            pass

    logger.info(
        "Ai worker reading %s as %s/%s",
        consumer.stream,
        consumer.group,
        consumer.consumer,
    )
    try:
        await stop.wait()
    finally:
        await stop_task(task)
        await redis.aclose()
        logger.info("Ai worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
