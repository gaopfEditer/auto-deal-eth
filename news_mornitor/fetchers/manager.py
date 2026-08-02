"""FetcherManager — 聚合多平台抓取。"""
from __future__ import annotations

import logging
from typing import Iterable

from news_mornitor.config import ENABLED_SOURCES
from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.binance_square import BinanceSquareFetcher
from news_mornitor.fetchers.bitget_square import BitgetSquareFetcher
from news_mornitor.fetchers.bybit_feed import BybitFeedFetcher
from news_mornitor.fetchers.cryptopanic import CryptoPanicFetcher
from news_mornitor.fetchers.farcaster import FarcasterFetcher
from news_mornitor.fetchers.okx_square import OkxSquareFetcher
from news_mornitor.fetchers.reddit_crypto import RedditCryptoFetcher
from news_mornitor.fetchers.tradingview_ideas import TradingViewIdeasFetcher
from news_mornitor.models import RawFetchItem

logger = logging.getLogger("CryptoPulse.FetcherManager")

_REGISTRY: dict[str, type[BaseFetcher]] = {
    "binance": BinanceSquareFetcher,
    "bitget": BitgetSquareFetcher,
    "okx": OkxSquareFetcher,
    "bybit": BybitFeedFetcher,
    "reddit": RedditCryptoFetcher,
    "tradingview": TradingViewIdeasFetcher,
    "cryptopanic": CryptoPanicFetcher,
    "farcaster": FarcasterFetcher,
}


def default_fetchers() -> list[BaseFetcher]:
    out: list[BaseFetcher] = []
    for key, cls in _REGISTRY.items():
        if key in ENABLED_SOURCES:
            out.append(cls())
    if not out:
        logger.warning("ENABLED_SOURCES 为空，回退 binance+reddit+tradingview+farcaster")
        out = [
            BinanceSquareFetcher(),
            RedditCryptoFetcher(),
            TradingViewIdeasFetcher(),
            FarcasterFetcher(),
        ]
    logger.info("启用抓取源: %s", ", ".join(f.name for f in out))
    return out


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
