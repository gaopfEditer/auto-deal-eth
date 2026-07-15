"""
突破回踩 + 维加斯/布林中轨 + 反转射击之星 — 两步状态机。

阶段 1：带量真突破 / 反转背景 → BREAKOUT_DETECTED / REVERSAL_WATCH（不弹窗）
阶段 2：缩量回踩中轨/维加斯/supply_wall 或顶部射击之星 → TRIGGER_SIGNAL
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from oi_mornitor.breakout_detector import is_valid_breakout, klines_to_df
from oi_mornitor.config import (
    PATTERN_BB_LENGTH,
    PATTERN_PIVOT_WINDOW,
    STRATEGY_PULLBACK_TOL,
    STRATEGY_PULLBACK_VOL_SHRINK,
)
from oi_mornitor.strategy.indicators import (
    detect_shooting_star,
    enrich_strategy_indicators,
    near_bb_upper,
    near_level,
    volume_shrink,
)

STATUS_SEARCHING = "SEARCHING"
STATUS_BREAKOUT = "BREAKOUT_DETECTED"
STATUS_WAIT_PULLBACK = "WAIT_PULLBACK"
STATUS_REVERSAL_WATCH = "REVERSAL_WATCH"
STATUS_TRIGGER = "TRIGGER_SIGNAL"
STATUS_EXPIRED = "EXPIRED"

STATUS_LABELS: dict[str, str] = {
    STATUS_SEARCHING: "扫描突破/反转",
    STATUS_BREAKOUT: "突破蓄势",
    STATUS_WAIT_PULLBACK: "等待回踩",
    STATUS_REVERSAL_WATCH: "反转观察",
    STATUS_TRIGGER: "扳机触发",
    STATUS_EXPIRED: "已过期",
}

SIGNAL_LONG_PULLBACK = "long_pullback"
SIGNAL_SHORT_SHOOTING_STAR = "short_shooting_star"


@dataclass
class PullbackSnapshot:
    status: str
    signal_type: str = ""
    supply_wall: float = 0.0
    anchor_level: float = 0.0
    anchor_kind: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "signal_type": self.signal_type,
            "supply_wall": self.supply_wall,
            "anchor_level": self.anchor_level,
            "anchor_kind": self.anchor_kind,
            "message": self.message,
        }


def _has_higher_low(df: pd.DataFrame) -> bool:
    win = PATTERN_PIVOT_WINDOW
    if len(df) < win * 2:
        return False
    work = df.copy()
    work["is_pivot_low"] = work["low"] == work["low"].rolling(win, center=True).min()
    lows = work[work["is_pivot_low"].fillna(False)].tail(2)
    if len(lows) < 2:
        return False
    return float(lows.iloc[1]["low"]) > float(lows.iloc[0]["low"])


def _detect_reversal_context(df: pd.DataFrame) -> bool:
    """价格曾低于布林中轨，现收回中轨上方且形成更高低点。"""
    if len(df) < PATTERN_BB_LENGTH + 10:
        return False
    last = df.iloc[-1]
    prev_slice = df.iloc[-12:-1]
    was_below = (prev_slice["close"] < prev_slice["bb_basis"]).any()
    now_above = float(last["close"]) > float(last["bb_basis"])
    return was_below and now_above and _has_higher_low(df)


def _pick_pullback_anchor(row: pd.Series, supply_wall: float) -> tuple[float, str] | None:
    """按优先级：supply_wall → 布林中轨 → 维加斯中线。"""
    candidates: list[tuple[float, str]] = []
    if supply_wall > 0:
        candidates.append((supply_wall, "supply_wall"))
    basis = float(row["bb_basis"]) if pd.notna(row["bb_basis"]) else 0.0
    if basis > 0:
        candidates.append((basis, "bb_mid"))
    vegas_mid = float(row["vegas_mid"]) if pd.notna(row["vegas_mid"]) else 0.0
    if vegas_mid > 0:
        candidates.append((vegas_mid, "vegas_mid"))
    for level, kind in candidates:
        if near_level(row, level, tol_pct=STRATEGY_PULLBACK_TOL):
            return level, kind
    return None


def evaluate_pullback_strategy(
    klines: list[list],
    *,
    current_status: str,
    state: dict[str, Any],
    oi_change_pct: float | None = None,
    oi_min_change_pct: float = -2.0,
) -> tuple[PullbackSnapshot, bool]:
    """
    单币种回踩/射击之星评估。
    返回 (快照, 是否发射扳机)。
    """
    df = klines_to_df(klines)
    min_len = max(PATTERN_BB_LENGTH, max(PATTERN_PIVOT_WINDOW * 2, 30))
    if len(df) < min_len:
        return PullbackSnapshot(status=current_status or STATUS_SEARCHING), False

    df = enrich_strategy_indicators(df)
    last = df.iloc[-1]
    supply_wall = float(state.get("supply_wall") or 0.0)

    if current_status in (STATUS_SEARCHING, STATUS_EXPIRED, ""):
        ok, wall = is_valid_breakout(df)
        if ok:
            return PullbackSnapshot(
                status=STATUS_BREAKOUT,
                supply_wall=wall,
                message=f"带量突破 supply_wall {wall:.4g}，等待缩量回踩",
            ), False
        if _detect_reversal_context(df):
            return PullbackSnapshot(
                status=STATUS_REVERSAL_WATCH,
                message="反转背景：HL + 收回布林中轨，观察顶部射击之星",
            ), False
        return PullbackSnapshot(status=STATUS_SEARCHING), False

    if current_status in (STATUS_BREAKOUT, STATUS_WAIT_PULLBACK):
        wall = supply_wall or float(state.get("supply_wall") or 0.0)
        anchor = _pick_pullback_anchor(last, wall)
        if not anchor:
            return PullbackSnapshot(
                status=STATUS_WAIT_PULLBACK,
                supply_wall=wall,
                message="突破后等待回踩中轨/维加斯/supply_wall",
            ), False
        level, kind = anchor
        if not volume_shrink(last, shrink_ratio=STRATEGY_PULLBACK_VOL_SHRINK):
            return PullbackSnapshot(
                status=STATUS_WAIT_PULLBACK,
                supply_wall=wall,
                anchor_level=level,
                anchor_kind=kind,
                message=f"触及 {kind} {level:.4g}，量能未萎缩",
            ), False
        if oi_change_pct is not None and oi_change_pct < oi_min_change_pct:
            return PullbackSnapshot(
                status=STATUS_WAIT_PULLBACK,
                supply_wall=wall,
                anchor_level=level,
                anchor_kind=kind,
                message=f"回踩成立但 OI 流出 {oi_change_pct:.2f}%",
            ), False
        return PullbackSnapshot(
            status=STATUS_TRIGGER,
            signal_type=SIGNAL_LONG_PULLBACK,
            supply_wall=wall,
            anchor_level=level,
            anchor_kind=kind,
            message=f"缩量回踩 {kind} {level:.4g} · 做多扳机",
        ), True

    if current_status == STATUS_REVERSAL_WATCH:
        at_lower = float(last["close"]) <= float(last["bb_lower"]) + float(last["bb_width"]) * 0.15
        if near_bb_upper(last) and detect_shooting_star(last, at_lower=at_lower):
            return PullbackSnapshot(
                status=STATUS_TRIGGER,
                signal_type=SIGNAL_SHORT_SHOOTING_STAR,
                message="反转后顶部射击之星 · 做空扳机",
            ), True
        return PullbackSnapshot(
            status=STATUS_REVERSAL_WATCH,
            message="反转背景成立，等待顶部射击之星",
        ), False

    return PullbackSnapshot(status=current_status), False
