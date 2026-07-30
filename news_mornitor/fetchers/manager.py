"""FetcherManager — 聚合多平台抓取（币安 / Bitget / OKX）。"""
from __future__ import annotations

import logging
from typing import Iterable

from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.binance_square import BinanceSquareFetcher
from news_mornitor.fetchers.bitget_square import BitgetSquareFetcher
from news_mornitor.fetchers.okx_square import OkxSquareFetcher
from news_mornitor.models import RawFetchItem

logger = logging.getLogger("CryptoPulse.FetcherManager")


def default_fetchers() -> list[BaseFetcher]:
    return [
        BinanceSquareFetcher(),
        BitgetSquareFetcher(),
        OkxSquareFetcher(),
    ]


class FetcherManager:
    def __init__(self, fetchers: Iterable[BaseFetcher] | None = None) -> None:
        self.fetchers: list[BaseFetcher] = list(fetchers) if fetchers else default_fetchers()

    def register(self, fetcher: BaseFetcher) -> None:
        self.fetchers.append(fetcher)

    async def fetch_all(self, *, limit_per_source: int = 40) -> list[RawFetchItem]:
        all_items: list[RawFetchItem] = []
        for fetcher in self.fetchers:
            try:
                items = await fetcher.fetch_trending(limit=limit_per_source)
                logger.info("[%s] 抓取 %d 条", fetcher.name, len(items))
                all_items.extend(items)
            except Exception as e:
                logger.exception("[%s] 抓取异常: %s", fetcher.name, e)
        return all_items
