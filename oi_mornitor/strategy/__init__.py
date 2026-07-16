"""OI + 形态回踩 / 射击之星策略模块。"""

# 注意：本包勿在 __init__ 里 import ws_monitor（会与 pattern_monitor 形成环）。
# 需要时：from oi_mornitor.strategy.ws_monitor import CoinWsMonitor

from oi_mornitor.strategy.pullback import (
    STATUS_BREAKOUT,
    STATUS_REVERSAL_WATCH,
    STATUS_SEARCHING,
    STATUS_TRIGGER,
    STATUS_WAIT_PULLBACK,
    PullbackSnapshot,
    evaluate_pullback_strategy,
)

__all__ = [
    "PullbackSnapshot",
    "STATUS_BREAKOUT",
    "STATUS_REVERSAL_WATCH",
    "STATUS_SEARCHING",
    "STATUS_TRIGGER",
    "STATUS_WAIT_PULLBACK",
    "evaluate_pullback_strategy",
]
