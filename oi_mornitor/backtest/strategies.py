"""回测 — 成本防守 + 推动止损策略。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskConfig:
    """单笔风控参数（百分比均为相对入场价）。"""

    initial_stop_pct: float = 2.0
    breakeven_trigger_pct: float = 1.0
    breakeven_buffer_pct: float = 0.08
    trail_start_pct: float = 2.5
    trail_pct: float = 1.2
    fee_pct: float = 0.04
    slippage_pct: float = 0.02
    max_bars: int = 48


@dataclass
class Position:
    side: str
    entry_price: float
    entry_bar: int
    stop: float
    breakeven_armed: bool = False
    trail_armed: bool = False
    highest: float = 0.0
    lowest: float = 0.0


@dataclass
class ClosedTrade:
    side: str
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    pnl_pct: float
    reason: str
    signal_type: str = ""


class CostDefenseTrailingManager:
    """
    成本防守 + 推动止损：

    1. 初始止损 initial_stop_pct
    2. 浮盈达 breakeven_trigger_pct → 止损抬至成本 + buffer（成本防守）
    3. 浮盈达 trail_start_pct → 按 trail_pct 追踪止损（推动止损）
    """

    def __init__(self, cfg: RiskConfig | None = None) -> None:
        self.cfg = cfg or RiskConfig()
        self.position: Position | None = None
        self.trades: list[ClosedTrade] = []

    @property
    def in_position(self) -> bool:
        return self.position is not None

    def open(self, side: str, price: float, bar_index: int, signal_type: str = "") -> None:
        slip = price * self.cfg.slippage_pct / 100.0
        entry = price + slip if side == "long" else price - slip
        if side == "long":
            stop = entry * (1 - self.cfg.initial_stop_pct / 100.0)
        else:
            stop = entry * (1 + self.cfg.initial_stop_pct / 100.0)
        self.position = Position(
            side=side,
            entry_price=entry,
            entry_bar=bar_index,
            stop=stop,
            highest=entry,
            lowest=entry,
        )
        self._pending_signal_type = signal_type

    def _close(self, exit_price: float, bar_index: int, reason: str) -> None:
        if not self.position:
            return
        pos = self.position
        slip = exit_price * self.cfg.slippage_pct / 100.0
        if pos.side == "long":
            px = exit_price - slip
            pnl = (px - pos.entry_price) / pos.entry_price * 100.0
        else:
            px = exit_price + slip
            pnl = (pos.entry_price - px) / pos.entry_price * 100.0
        pnl -= self.cfg.fee_pct * 2
        self.trades.append(
            ClosedTrade(
                side=pos.side,
                entry_bar=pos.entry_bar,
                exit_bar=bar_index,
                entry_price=pos.entry_price,
                exit_price=px,
                pnl_pct=pnl,
                reason=reason,
                signal_type=getattr(self, "_pending_signal_type", ""),
            )
        )
        self.position = None

    def update_bar(self, *, high: float, low: float, close: float, bar_index: int) -> str | None:
        """每根 K 线更新持仓；返回平仓原因或 None。"""
        pos = self.position
        if not pos:
            return None

        bars_held = bar_index - pos.entry_bar
        if bars_held >= self.cfg.max_bars:
            self._close(close, bar_index, "timeout")
            return "timeout"

        if pos.side == "long":
            pos.highest = max(pos.highest, high)
            profit_pct = (pos.highest - pos.entry_price) / pos.entry_price * 100.0
            if not pos.breakeven_armed and profit_pct >= self.cfg.breakeven_trigger_pct:
                pos.stop = max(
                    pos.stop,
                    pos.entry_price * (1 + self.cfg.breakeven_buffer_pct / 100.0),
                )
                pos.breakeven_armed = True
            if not pos.trail_armed and profit_pct >= self.cfg.trail_start_pct:
                pos.trail_armed = True
            if pos.trail_armed:
                trail_stop = pos.highest * (1 - self.cfg.trail_pct / 100.0)
                pos.stop = max(pos.stop, trail_stop)
            if low <= pos.stop:
                self._close(pos.stop, bar_index, "stop")
                return "stop"
        else:
            pos.lowest = min(pos.lowest, low)
            profit_pct = (pos.entry_price - pos.lowest) / pos.entry_price * 100.0
            if not pos.breakeven_armed and profit_pct >= self.cfg.breakeven_trigger_pct:
                pos.stop = min(
                    pos.stop,
                    pos.entry_price * (1 - self.cfg.breakeven_buffer_pct / 100.0),
                )
                pos.breakeven_armed = True
            if not pos.trail_armed and profit_pct >= self.cfg.trail_start_pct:
                pos.trail_armed = True
            if pos.trail_armed:
                trail_stop = pos.lowest * (1 + self.cfg.trail_pct / 100.0)
                pos.stop = min(pos.stop, trail_stop)
            if high >= pos.stop:
                self._close(pos.stop, bar_index, "stop")
                return "stop"

        return None
