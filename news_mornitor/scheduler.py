"""定时抓取调度（替代 Redis Cron）。"""
from __future__ import annotations

import asyncio
import logging

from news_mornitor.config import FETCH_INTERVAL_SEC
from news_mornitor.pipeline.ingest import IngestPipeline

logger = logging.getLogger("CryptoPulse.Scheduler")


async def run_scheduler(*, interval_sec: int = FETCH_INTERVAL_SEC) -> None:
    pipeline = IngestPipeline()
    logger.info("调度启动，间隔 %ss", interval_sec)
    while True:
        try:
            await pipeline.run_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("调度轮次失败: %s", e)
        await asyncio.sleep(interval_sec)
