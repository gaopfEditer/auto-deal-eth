"""布林带 / 维加斯 / 量能指标 — 与 Pine 脚本参数对齐。"""
from __future__ import annotations

import pandas as pd

from oi_mornitor.config import (
    PATTERN_BB_LENGTH,
    PATTERN_BB_MULT,
    STRATEGY_SHOOT_WICK_MAX_RATIO,
    STRATEGY_SHOOT_WICK_RATIO,
    STRATEGY_VEGAS_PERIODS,
)


def enrich_strategy_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["bb_basis"] = out["close"].rolling(PATTERN_BB_LENGTH).mean()
    out["bb_std"] = out["close"].rolling(PATTERN_BB_LENGTH).std(ddof=0)
    out["bb_upper"] = out["bb_basis"] + PATTERN_BB_MULT * out["bb_std"]
    out["bb_lower"] = out["bb_basis"] - PATTERN_BB_MULT * out["bb_std"]
    out["bb_width"] = out["bb_upper"] - out["bb_lower"]
    out["vol_sma20"] = out["volume"].rolling(20).mean()

    for i, period in enumerate(STRATEGY_VEGAS_PERIODS, start=1):
        out[f"vegas_e{i}"] = out["close"].ewm(span=period, adjust=False).mean()
    vegas_cols = [f"vegas_e{i}" for i in range(1, len(STRATEGY_VEGAS_PERIODS) + 1)]
    out["vegas_mid"] = out[vegas_cols].mean(axis=1)
    out["vegas_min"] = out[vegas_cols].min(axis=1)
    out["vegas_max"] = out[vegas_cols].max(axis=1)
    return out


def min_dist_to_level(row: pd.Series, level: float) -> float:
    if pd.isna(level) or level <= 0:
        return float("inf")
    return min(
        abs(float(row["high"]) - level),
        abs(float(row["low"]) - level),
        abs(float(row["close"]) - level),
    )


def near_level(row: pd.Series, level: float, *, tol_pct: float) -> bool:
    """价格是否贴近支撑/中轨（相对价位容差）。"""
    if pd.isna(level) or level <= 0:
        return False
    tol = level * tol_pct
    low = float(row["low"])
    close = float(row["close"])
    return low <= level + tol and close >= level - tol


def volume_shrink(row: pd.Series, *, shrink_ratio: float) -> bool:
    vol_sma = float(row["vol_sma20"]) if pd.notna(row["vol_sma20"]) else 0.0
    if vol_sma <= 0:
        return False
    return float(row["volume"]) < vol_sma * shrink_ratio


def detect_shooting_star(
    row: pd.Series,
    *,
    at_lower: bool = False,
    wick_ratio: float = STRATEGY_SHOOT_WICK_RATIO,
    max_ratio: float = STRATEGY_SHOOT_WICK_MAX_RATIO,
) -> bool:
    """射击之星 — 与 tradingview-bollinger-wicks.pine 逻辑一致。"""
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    body = abs(c - o)
    upper_w = h - max(o, c)
    lower_w = min(o, c) - l
    if body <= 0 or upper_w <= 0:
        return False
    if upper_w < body * wick_ratio or upper_w > body * max_ratio:
        return False
    lower_ok = lower_w <= 0 or upper_w > 0 and lower_w * 2.0 < upper_w
    if not lower_ok:
        return False
    if at_lower and c >= o:
        return False
    return True


def near_bb_upper(row: pd.Series, *, pct_in_band: float = 0.85) -> bool:
    """收盘位于布林带上沿区域（默认上 15% 带宽内）。"""
    upper = float(row["bb_upper"])
    lower = float(row["bb_lower"])
    width = upper - lower
    if width <= 0 or pd.isna(width):
        return False
    return float(row["close"]) >= lower + width * pct_in_band
