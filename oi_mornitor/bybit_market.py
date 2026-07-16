"""兼容旧导入：Bybit 已并入 exchange_sources 多源链。"""
from __future__ import annotations

from oi_mornitor.exchange_sources import (
    SOURCE_LABELS,
    ExchangeFeed,
    fetch_bybit,
    fetch_fallback_feed,
)

SOURCE_ID = "bybit"
SOURCE_LABEL = f"{SOURCE_LABELS['bybit']}（币安限流兜底）"


async def fetch_bybit_linear_tickers(session, *, base_url: str | None = None):
    feed = await fetch_bybit(session)
    return feed.tickers if feed else []


def oi_map_from_bybit_tickers(tickers):
    return {
        str(t["symbol"]): float(t["openInterest"])
        for t in tickers
        if t.get("openInterest")
    }


__all__ = [
    "SOURCE_ID",
    "SOURCE_LABEL",
    "ExchangeFeed",
    "fetch_bybit_linear_tickers",
    "oi_map_from_bybit_tickers",
    "fetch_fallback_feed",
]
