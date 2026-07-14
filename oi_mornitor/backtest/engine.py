"""历史 K 线回测引擎 — 回踩做多 / 反转射击之星做空 + 成本防守止损。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from oi_mornitor.breakout_detector import klines_to_df
from oi_mornitor.strategy.pullback import (
    SIGNAL_LONG_PULLBACK,
    SIGNAL_SHORT_SHOOTING_STAR,
    STATUS_TRIGGER,
    evaluate_pullback_strategy,
)
from oi_mornitor.backtest.strategies import ClosedTrade, CostDefenseTrailingManager, RiskConfig


@dataclass
class BacktestResult:
    symbol: str
    interval: str
    bars: int
    signals: int
    trades: list[ClosedTrade] = field(default_factory=list)
    win_rate: float = 0.0
    avg_pnl_pct: float = 0.0
    total_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "bars": self.bars,
            "signals": self.signals,
            "trade_count": len(self.trades),
            "win_rate": round(self.win_rate, 2),
            "avg_pnl_pct": round(self.avg_pnl_pct, 3),
            "total_pnl_pct": round(self.total_pnl_pct, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 3),
            "trades": [
                {
                    "side": t.side,
                    "entry_bar": t.entry_bar,
                    "exit_bar": t.exit_bar,
                    "entry_price": round(t.entry_price, 6),
                    "exit_price": round(t.exit_price, 6),
                    "pnl_pct": round(t.pnl_pct, 3),
                    "reason": t.reason,
                    "signal_type": t.signal_type,
                }
                for t in self.trades
            ],
        }


def run_pullback_backtest(
    klines: list[list],
    *,
    symbol: str = "SYMBOL",
    interval: str = "1h",
    risk: RiskConfig | None = None,
    warmup: int = 60,
) -> BacktestResult:
    """
    逐 K 线回放 evaluate_pullback_strategy，触发信号下一根开盘价入场。
    """
    df = klines_to_df(klines)
    n = len(df)
    if n <= warmup + 5:
        return BacktestResult(symbol=symbol, interval=interval, bars=n, signals=0)

    mgr = CostDefenseTrailingManager(risk)
    status = "SEARCHING"
    state: dict[str, Any] = {"supply_wall": 0.0}
    signals = 0
    equity = 100.0
    peak = equity
    max_dd = 0.0
    pending_entry: tuple[str, str] | None = None

    for i in range(warmup, n):
        window = klines[: i + 1]
        row = df.iloc[i]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        open_px = float(row["open"])

        if mgr.in_position:
            mgr.update_bar(high=high, low=low, close=close, bar_index=i)
            if not mgr.in_position and mgr.trades:
                equity *= 1 + mgr.trades[-1].pnl_pct / 100.0
                peak = max(peak, equity)
                dd = (peak - equity) / peak * 100.0
                max_dd = max(max_dd, dd)

        if pending_entry and not mgr.in_position:
            side, sig_type = pending_entry
            mgr.open(side, open_px, i, signal_type=sig_type)
            pending_entry = None
            status = "SEARCHING"
            state = {"supply_wall": 0.0}

        snap, fire = evaluate_pullback_strategy(
            window,
            current_status=status,
            state=state,
            oi_change_pct=None,
        )

        if fire and snap.status == STATUS_TRIGGER and not mgr.in_position and not pending_entry:
            signals += 1
            if snap.signal_type == SIGNAL_LONG_PULLBACK:
                pending_entry = ("long", snap.signal_type)
            elif snap.signal_type == SIGNAL_SHORT_SHOOTING_STAR:
                pending_entry = ("short", snap.signal_type)
            status = "SEARCHING"
            state = {"supply_wall": 0.0}
        elif not fire:
            status = snap.status
            state = {
                "supply_wall": snap.supply_wall or state.get("supply_wall", 0.0),
                "anchor_level": snap.anchor_level,
                "anchor_kind": snap.anchor_kind,
            }

    trades = mgr.trades
    wins = sum(1 for t in trades if t.pnl_pct > 0)
    win_rate = wins / len(trades) * 100.0 if trades else 0.0
    avg_pnl = sum(t.pnl_pct for t in trades) / len(trades) if trades else 0.0
    total_pnl = sum(t.pnl_pct for t in trades)

    return BacktestResult(
        symbol=symbol,
        interval=interval,
        bars=n,
        signals=signals,
        trades=trades,
        win_rate=win_rate,
        avg_pnl_pct=avg_pnl,
        total_pnl_pct=total_pnl,
        max_drawdown_pct=max_dd,
    )
