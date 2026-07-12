"""
带量真突破检测 + 回踩扳机 — Pandas 矩阵过滤。

第一步：is_valid_breakout → 标记 BREAKOUT_DETECTED（不弹窗）
第二步：is_pullback_trigger → 演进 TRIGGER_SIGNAL（弹窗）
"""
from __future__ import annotations

import pandas as pd

from oi_mornitor.config import (
    BREAKOUT_LOOKBACK,
    BREAKOUT_VOL_MULT,
    BREAKOUT_BODY_RATIO,
    PULLBACK_VOL_SHRINK_RATIO,
    PULLBACK_TOUCH_TOLERANCE,
)

KLINE_COLS = ("open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume")


def klines_to_df(klines: list[list]) -> pd.DataFrame:
    """Binance klines → OHLCV DataFrame。"""
    if not klines:
        return pd.DataFrame(columns=list(KLINE_COLS))
    rows = []
    for row in klines:
        rows.append(
            {
                "open_time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time": int(row[6]),
                "quote_volume": float(row[7]),
            }
        )
    return pd.DataFrame(rows)


def is_valid_breakout(df: pd.DataFrame, lookback: int = BREAKOUT_LOOKBACK) -> tuple[bool, float]:
    """
    判断当前最新结账的 K 线是否发生了标准带量真突破。
    返回 (是否突破, supply_wall 价格)。
    """
    if len(df) < lookback + 1:
        return False, 0.0

    hist_df = df.iloc[-lookback - 1 : -1].copy()
    current_k = df.iloc[-1]

    top_vol_indices = hist_df["volume"].nlargest(3).index
    supply_wall = float(hist_df.loc[top_vol_indices, "high"].max())

    is_price_break = float(current_k["close"]) > supply_wall

    vol_sma20 = float(hist_df["volume"].tail(20).mean())
    is_volume_heavy = float(current_k["volume"]) > (vol_sma20 * BREAKOUT_VOL_MULT)

    bar_range = float(current_k["high"]) - float(current_k["low"])
    body_range = float(current_k["close"]) - float(current_k["open"])
    is_solid_bull = body_range > 0 and bar_range > 0 and (body_range / bar_range) > BREAKOUT_BODY_RATIO

    if is_price_break and is_volume_heavy and is_solid_bull:
        return True, supply_wall

    return False, 0.0


def is_pullback_trigger(
    df: pd.DataFrame,
    supply_wall: float,
    *,
    lookback: int = BREAKOUT_LOOKBACK,
) -> bool:
    """
    回踩扣动扳机：最低价触及 supply_wall 支撑，且成交量极度萎缩。
    """
    if len(df) < lookback + 1 or supply_wall <= 0:
        return False

    hist_df = df.iloc[-lookback - 1 : -1]
    current_k = df.iloc[-1]

    vol_sma20 = float(hist_df["volume"].tail(20).mean())
    if vol_sma20 <= 0:
        return False

    tol = supply_wall * PULLBACK_TOUCH_TOLERANCE
    low = float(current_k["low"])
    close = float(current_k["close"])
    volume = float(current_k["volume"])

    # 回踩踩线：低点触及供给墙附近，收盘仍站稳墙上
    is_retest = (low <= supply_wall + tol) and (close > supply_wall)
    is_volume_shrink = volume < vol_sma20 * PULLBACK_VOL_SHRINK_RATIO

    return is_retest and is_volume_shrink
