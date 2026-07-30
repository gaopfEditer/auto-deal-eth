"""Fetcher 抽象基类。"""
from __future__ import annotations

import abc
import asyncio
import logging

from news_mornitor.config import REQUEST_DELAY_SEC
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.Fetcher")


class BaseFetcher(abc.ABC):
    platform: Platform
    name: str = "base"

    def __init__(self, *, request_delay: float = REQUEST_DELAY_SEC) -> None:
        self.request_delay = request_delay

    @abc.abstractmethod
    async def fetch_trending(self, *, limit: int = 40) -> list[RawFetchItem]:
        """拉取热门/Trending 帖子。"""

    async def _sleep(self) -> None:
        if self.request_delay > 0:
            await asyncio.sleep(self.request_delay)

    def _log_error(self, exc: BaseException, context: str = "") -> None:
        logger.error("[%s] %s: %s", self.name, context or "fetch failed", exc, exc_info=True)
