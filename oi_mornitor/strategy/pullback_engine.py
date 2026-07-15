"""形态页关注列表 × 回踩/Vegas/射击之星策略引擎。"""
from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from oi_mornitor.config import (
    FAPI_BASE_URL,
    STRATEGY_KLINE_INTERVAL,
    STRATEGY_OI_MIN_CHANGE_PCT,
)
from oi_mornitor.pattern_monitor import PatternMonitorEngine, fetch_pattern_klines_batch
from oi_mornitor.strategy.pullback import STATUS_TRIGGER, STATUS_LABELS, evaluate_pullback_strategy
from oi_mornitor.strategy.pullback_state_tracker import PullbackStateTracker

logger = logging.getLogger("OI_Radar")


class PullbackStrategyEngine:
    """与 PatternMonitorEngine 共用 watchlist，额外跑回踩/射击之星状态机。"""

    def __init__(self, pattern_engine: PatternMonitorEngine | None = None) -> None:
        self.pattern_engine = pattern_engine or PatternMonitorEngine()
        self.tracker = PullbackStateTracker()
        self._last_alerts: list[dict[str, Any]] = []
        self._last_states: list[dict[str, Any]] = []
        self._last_scan_ts: float = 0.0
        self._oi_change_pct: dict[str, float] = {}

    def set_oi_change_pct(self, symbol: str, pct: float) -> None:
        self._oi_change_pct[symbol.upper()] = pct

    @property
    def last_alerts(self) -> list[dict[str, Any]]:
        return list(self._last_alerts)

    @property
    def last_states(self) -> list[dict[str, Any]]:
        return list(self._last_states)

    def get_payload(self) -> dict[str, Any]:
        return {
            "pullback_scan_ts": self._last_scan_ts,
            "pullback_states": self._last_states,
            "pullback_alerts": self._last_alerts,
        }

    async def scan(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = FAPI_BASE_URL,
        scan_ts: float | None = None,
        pool_rows: list[dict[str, Any]] | None = None,
        fallback_symbols: list[str] | None = None,
        interval: str = STRATEGY_KLINE_INTERVAL,
    ) -> list[dict[str, Any]]:
        if pool_rows:
            self.pattern_engine.ensure_auto_watchlist(
                pool_rows, fallback_symbols=fallback_symbols
            )

        watchlist = self.pattern_engine.tracker.list_watchlist()
        if not watchlist:
            self._last_alerts = []
            self._last_states = []
            self._last_scan_ts = scan_ts or time.time()
            return []

        self.tracker.expire_stale()
        symbols = [w.symbol for w in watchlist]
        for sym in symbols:
            self.tracker.ensure_symbol(sym)

        klines_map = await fetch_pattern_klines_batch(
            session,
            base_url=base_url,
            symbols=symbols,
            interval=interval,
        )

        alerts: list[dict[str, Any]] = []
        states: list[dict[str, Any]] = []

        for item in watchlist:
            sym = item.symbol
            klines = klines_map.get(sym) or []
            if not klines:
                states.append(self._state_dict(sym, interval, None))
                continue

            kline_close_time = int(klines[-1][6])
            row = self.tracker.get_state(sym)
            current_status = row.status if row else "SEARCHING"

            if row and row.trigger_emitted:
                states.append(self._state_dict(sym, interval, row))
                continue

            if row and kline_close_time <= row.last_kline_close_time:
                states.append(self._state_dict(sym, interval, row))
                continue

            state_data = {
                "supply_wall": row.supply_wall if row else 0.0,
                "anchor_level": row.anchor_level if row else 0.0,
                "anchor_kind": row.anchor_kind if row else "",
            }
            oi_pct = self._oi_change_pct.get(sym)

            snap, fire = evaluate_pullback_strategy(
                klines,
                current_status=current_status,
                state=state_data,
                oi_change_pct=oi_pct,
                oi_min_change_pct=STRATEGY_OI_MIN_CHANGE_PCT,
            )

            if snap.status != STATUS_TRIGGER:
                self.tracker.save_state(
                    sym,
                    status=snap.status,
                    signal_type=snap.signal_type,
                    supply_wall=snap.supply_wall or state_data["supply_wall"],
                    anchor_level=snap.anchor_level,
                    anchor_kind=snap.anchor_kind,
                    kline_close_time=kline_close_time,
                    message=snap.message,
                )
                if snap.status in ("BREAKOUT_DETECTED", "REVERSAL_WATCH"):
                    logger.info("📐 回踩阶段1 %s [%s] %s", sym, snap.status, snap.message)

            elif fire:
                self.tracker.mark_triggered(sym, kline_close_time, snap.signal_type)
                alert = {
                    "symbol": sym,
                    "type": snap.signal_type,
                    "interval": interval,
                    "status": STATUS_TRIGGER,
                    "status_label": STATUS_LABELS[STATUS_TRIGGER],
                    "signal_type": snap.signal_type,
                    "supply_wall": snap.supply_wall,
                    "anchor_level": snap.anchor_level,
                    "anchor_kind": snap.anchor_kind,
                    "last_price": float(klines[-1][4]),
                    "message": snap.message,
                    "scan_ts": scan_ts or time.time(),
                    "kline_close_time": kline_close_time,
                    "oi_change_pct": oi_pct,
                }
                alerts.append(alert)
                logger.info("🎯 回踩扳机 %s %s", sym, snap.message)

            updated = self.tracker.get_state(sym)
            states.append(self._state_dict(sym, interval, updated))

        self._last_alerts = alerts
        self._last_states = states
        self._last_scan_ts = scan_ts or time.time()
        return alerts

    def _state_dict(self, symbol: str, interval: str, row: Any) -> dict[str, Any]:
        if row is None:
            return {
                "symbol": symbol,
                "interval": interval,
                "status": "SEARCHING",
                "status_label": STATUS_LABELS["SEARCHING"],
                "message": "等待 K 线",
            }
        return {
            "symbol": row.symbol,
            "interval": interval,
            "status": row.status,
            "status_label": STATUS_LABELS.get(row.status, row.status),
            "signal_type": row.signal_type,
            "supply_wall": row.supply_wall,
            "anchor_level": row.anchor_level,
            "anchor_kind": row.anchor_kind,
            "message": row.message,
            "updated_at": row.updated_at,
            "trigger_emitted": row.trigger_emitted,
        }
