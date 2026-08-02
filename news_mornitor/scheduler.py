"""定时抓取调度：尊重停止/开始开关；先睡满间隔再抓。"""
from __future__ import annotations

import asyncio
import logging

from news_mornitor.config import FETCH_INTERVAL_SEC
from news_mornitor.pipeline.fetch_control import is_fetch_enabled
from news_mornitor.pipeline.ingest_gate import run_ingest_gated, seconds_until_next

logger = logging.getLogger("CryptoPulse.Scheduler")


async def run_scheduler(*, interval_sec: int = FETCH_INTERVAL_SEC) -> None:
    interval = max(60, int(interval_sec))
    first_wait = seconds_until_next(interval_sec=interval)
    if first_wait <= 0:
        first_wait = float(interval)
    logger.info("调度启动：%ss 后检查首轮，之后每 %ss（可用前端停止/开始）", int(first_wait), interval)
    await asyncio.sleep(first_wait)
    while True:
        try:
            if not is_fetch_enabled():
                logger.info("定时抓取已停止，本轮跳过")
            else:
                result = await run_ingest_gated(force=False, interval_sec=interval)
                if result.get("skipped"):
                    logger.info("本轮跳过: %s", result.get("reason"))
                else:
                    logger.info("调度抓取完成 fetched=%s", result.get("fetched"))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("调度轮次失败: %s", e)
        # 停止时也短睡，便于响应「开始」后不必等满 30 分钟才醒
        if is_fetch_enabled():
            await asyncio.sleep(interval)
        else:
            await asyncio.sleep(min(30, interval))
