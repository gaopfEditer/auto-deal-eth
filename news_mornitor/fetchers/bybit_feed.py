"""Bybit Feed — 尝试公开接口；失败本轮跳过（不回退 mock）。"""
from __future__ import annotations

import logging

from news_mornitor.config import USE_MOCK_FETCHER
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.common import build_mock_items, http_get_json, parse_generic_feed
from news_mornitor.fetchers.mock_posts import mock_home_url, samples_for
from news_mornitor.models import Platform, RawFetchItem

logger = logging.getLogger("CryptoPulse.Bybit")

_BYBIT_CANDIDATES = [
    "https://api2.bybit.com/spot/api/web/content/feed/list",
    "https://api2.bybit.com/spot/api/web/community/feed/list",
]

_MOCK = samples_for(Platform.BYBIT, n=16, offset=9)


def _mock_url(_eid: str) -> str:
    return mock_home_url(Platform.BYBIT)


def _real_url(eid: str) -> str:
    return f"https://www.bybit.com/trade/spot/feed/{eid}"


class BybitFeedFetcher(BaseFetcher):
    platform = Platform.BYBIT
    name = "bybit_feed"

    async def fetch_trending(self, *, limit: int = 40) -> list[RawFetchItem]:
        if USE_MOCK_FETCHER:
            return build_mock_items(
                Platform.BYBIT, _MOCK, limit=limit, url_builder=_mock_url
            )

        for url in _BYBIT_CANDIDATES:
            data = await http_get_json(url, name=self.name)
            if not data:
                continue
            items = parse_generic_feed(
                data,
                platform=Platform.BYBIT,
                url_builder=_real_url,
            )
            if items:
                await self._sleep()
                return items[:limit]

        logger.warning("[%s] 公开 Feed API 不可用，尝试 CDP 9222", self.name)
        try:
            from news_mornitor.fetchers.cdp_square import fetch_via_cdp

            cdp_items = await fetch_via_cdp(Platform.BYBIT, limit=limit)
            if cdp_items:
                logger.info("[%s] CDP 回退命中 %d 条", self.name, len(cdp_items))
                return cdp_items[:limit]
        except Exception as e:
            logger.warning("[%s] CDP 回退失败: %s", self.name, e)
        return []
