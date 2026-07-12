"""
Taker 主动成交资金流 — 基于 5m K 线聚合多周期净额与成交额。

合约榜用 fapi/klines；现货榜用 spot/api/v3/klines。
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from oi_mornitor.config import HTTP_TIMEOUT_SEC, OI_OI_BATCH_CONCURRENCY

# 与前端 tf-btn / radar OI_TF_WINDOWS 对齐（5m K 线根数）
TF_KLINE_BARS: dict[str, int] = {
    "15m": 3,
    "30m": 6,
    "1h": 12,
    "4h": 48,
    "1d": 288,
}

MAX_KLINE_LIMIT = max(TF_KLINE_BARS.values())


def _window_from_klines(klines: list[list[Any]], bars: int) -> dict[str, float]:
    """单周期：净主动流入 = Σ(2×Taker买报价额 − 报价额)；成交额 = Σ报价额。"""
    if not klines or bars <= 0:
        return {"net_usd": 0.0, "volume_usd": 0.0}

    slice_ = klines[-bars:] if len(klines) >= bars else klines
    quote_sum = 0.0
    net_sum = 0.0
    for row in slice_:
        quote = float(row[7])
        taker_buy_quote = float(row[10])
        quote_sum += quote
        net_sum += 2.0 * taker_buy_quote - quote
    return {"net_usd": round(net_sum, 2), "volume_usd": round(quote_sum, 2)}


def build_flow_by_tf(klines: list[list[Any]]) -> dict[str, dict[str, float]]:
    return {label: _window_from_klines(klines, bars) for label, bars in TF_KLINE_BARS.items()}


def empty_flow_by_tf() -> dict[str, dict[str, float]]:
    return {label: {"net_usd": 0.0, "volume_usd": 0.0} for label in TF_KLINE_BARS}


async def _fetch_klines_flow_batch(
    session: aiohttp.ClientSession,
    *,
    kline_url: str,
    symbols: list[str],
) -> dict[str, dict[str, dict[str, float]]]:
    if not symbols:
        return {}

    sem = asyncio.Semaphore(OI_OI_BATCH_CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    out: dict[str, dict[str, dict[str, float]]] = {}

    async def _one(sym: str) -> None:
        url = f"{kline_url}?symbol={sym}&interval=5m&limit={MAX_KLINE_LIMIT}"
        async with sem:
            try:
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status != 200:
                        out[sym] = empty_flow_by_tf()
                        return
                    data = await resp.json()
                    if not isinstance(data, list):
                        out[sym] = empty_flow_by_tf()
                        return
                    out[sym] = build_flow_by_tf(data)
            except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError, IndexError):
                out[sym] = empty_flow_by_tf()

    await asyncio.gather(*[_one(s) for s in symbols])
    return out


async def fetch_taker_flow_batch(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    symbols: list[str],
) -> dict[str, dict[str, dict[str, float]]]:
    """并发拉取 U 本位永续 5m K 线 Taker 净流。"""
    return await _fetch_klines_flow_batch(
        session,
        kline_url=f"{base_url.rstrip('/')}/fapi/v1/klines",
        symbols=symbols,
    )


async def fetch_spot_taker_flow_batch(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    symbols: list[str],
) -> dict[str, dict[str, dict[str, float]]]:
    """并发拉取现货 5m K 线 Taker 净流（与合约池同 symbol）。"""
    return await _fetch_klines_flow_batch(
        session,
        kline_url=f"{base_url.rstrip('/')}/api/v3/klines",
        symbols=symbols,
    )
