"""fapi 全市场快照与 OI 量级分层（大象 / 中场）。"""
from __future__ import annotations

from typing import Any, Optional

from oi_mornitor.config import OI_TIER_HEAVY_MIN_USD, OI_TIER_MID_MIN_USD

TIER_HEAVY = "heavyweight"
TIER_MID = "midweight"


def oi_usd(oi_base: float, price: float) -> float:
    return oi_base * price


def classify_oi_tier(oi_usd_value: float) -> Optional[str]:
    """
    大象级 ≥ 5000万 USD；中场级 1000万～5000万；< 1000万 排除。
    """
    if oi_usd_value < OI_TIER_MID_MIN_USD:
        return None
    if oi_usd_value >= OI_TIER_HEAVY_MIN_USD:
        return TIER_HEAVY
    return TIER_MID


def tier_label(tier: str) -> str:
    return {"heavyweight": "大象", "midweight": "中场"}.get(tier, tier)


def filter_usdt_perpetuals(tickers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in tickers:
        sym = str(item.get("symbol", ""))
        if not sym.endswith("USDT"):
            continue
        if "UPUSDT" in sym or "DOWNUSDT" in sym:
            continue
        out.append(item)
    return out


def pool_meta_from_counts(
    *,
    ticker_count: int,
    heavy: int,
    mid: int,
    excluded: int,
    eligible: int,
) -> dict[str, Any]:
    return {
        "mode": "fapi_ticker_aggregate",
        "ticker_count": ticker_count,
        "heavyweight_count": heavy,
        "midweight_count": mid,
        "excluded_sub_10m": excluded,
        "eligible_count": eligible,
        "tier_mid_min_usd": OI_TIER_MID_MIN_USD,
        "tier_heavy_min_usd": OI_TIER_HEAVY_MIN_USD,
    }
