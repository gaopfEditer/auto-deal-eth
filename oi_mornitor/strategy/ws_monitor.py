"""币安 U 本位合约 WebSocket 本地监控 — K 线 + OI + 回踩/射击之星策略。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Callable

import aiohttp
import websockets

from oi_mornitor.config import (
    FAPI_BASE_URL,
    FSTREAM_WS_BASE,
    STRATEGY_KLINE_INTERVAL,
    STRATEGY_KLINE_LIMIT,
    STRATEGY_OI_MIN_CHANGE_PCT,
    proxy_url,
)
from oi_mornitor.pattern_monitor import fetch_pattern_klines_batch
from oi_mornitor.strategy.pullback import STATUS_TRIGGER, evaluate_pullback_strategy
from oi_mornitor.strategy.pullback_state_tracker import PullbackStateTracker

logger = logging.getLogger("CoinWsMonitor")

AlertCallback = Callable[[dict[str, Any]], None]


class CoinWsMonitor:
    """
    无感知监听多币种 K 线收盘 + 持仓量变化，运行回踩/Vegas/射击之星状态机。

    用法::

        monitor = CoinWsMonitor(["BTCUSDT", "ETHUSDT"])
        await monitor.start(on_alert=lambda a: print(a))
    """

    def __init__(
        self,
        symbols: list[str],
        *,
        interval: str = STRATEGY_KLINE_INTERVAL,
        on_alert: AlertCallback | None = None,
    ) -> None:
        self.symbols = [s.strip().upper() for s in symbols if s.strip()]
        self.interval = interval
        self.on_alert = on_alert
        self.tracker = PullbackStateTracker()
        self._oi_by_symbol: dict[str, float] = {}
        self._oi_history: dict[str, deque[tuple[float, float]]] = {
            s: deque(maxlen=60) for s in self.symbols
        }
        self._running = False

    def _stream_path(self) -> str:
        parts: list[str] = []
        for sym in self.symbols:
            low = sym.lower()
            parts.append(f"{low}@kline_{self.interval}")
            parts.append(f"{low}@openInterest")
        return "/".join(parts)

    def _ws_url(self) -> str:
        return f"{FSTREAM_WS_BASE.rstrip('/')}/stream?streams={self._stream_path()}"

    def _oi_change_pct(self, symbol: str) -> float | None:
        hist = self._oi_history.get(symbol)
        if not hist or len(hist) < 2:
            return None
        first_oi = hist[0][1]
        last_oi = hist[-1][1]
        if first_oi <= 0:
            return None
        return (last_oi - first_oi) / first_oi * 100.0

    async def _bootstrap_klines(self, session: aiohttp.ClientSession) -> None:
        """冷启动：REST 拉历史 K 线，避免 WS 刚连上时指标不足。"""
        if not self.symbols:
            return
        klines_map = await fetch_pattern_klines_batch(
            session,
            base_url=FAPI_BASE_URL,
            symbols=self.symbols,
            interval=self.interval,
            limit=STRATEGY_KLINE_LIMIT,
        )
        for sym in self.symbols:
            self.tracker.ensure_symbol(sym)
            klines = klines_map.get(sym) or []
            if len(klines) < 30:
                continue
            row = self.tracker.get_state(sym)
            status = row.status if row else "SEARCHING"
            state = {"supply_wall": row.supply_wall if row else 0.0}
            snap, _ = evaluate_pullback_strategy(
                klines,
                current_status=status,
                state=state,
                oi_change_pct=self._oi_change_pct(sym),
                oi_min_change_pct=STRATEGY_OI_MIN_CHANGE_PCT,
            )
            if row and row.trigger_emitted:
                continue
            self.tracker.save_state(
                sym,
                status=snap.status,
                signal_type=snap.signal_type,
                supply_wall=snap.supply_wall or state.get("supply_wall", 0.0),
                anchor_level=snap.anchor_level,
                anchor_kind=snap.anchor_kind,
                kline_close_time=int(klines[-1][6]),
                message=snap.message,
            )

    async def _handle_kline_closed(self, symbol: str, kline: dict[str, Any]) -> None:
        if not kline.get("x"):
            return
        self.tracker.ensure_symbol(symbol)
        row = self.tracker.get_state(symbol)
        if row and row.trigger_emitted:
            return

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(trust_env=True) as session:
            klines_map = await fetch_pattern_klines_batch(
                session,
                base_url=FAPI_BASE_URL,
                symbols=[symbol],
                interval=self.interval,
                limit=STRATEGY_KLINE_LIMIT,
            )
        klines = klines_map.get(symbol) or []
        if not klines:
            return

        kline_close_time = int(klines[-1][6])
        if row and kline_close_time <= row.last_kline_close_time:
            return

        state = {"supply_wall": row.supply_wall if row else 0.0}
        status = row.status if row else "SEARCHING"
        snap, fire = evaluate_pullback_strategy(
            klines,
            current_status=status,
            state=state,
            oi_change_pct=self._oi_change_pct(symbol),
            oi_min_change_pct=STRATEGY_OI_MIN_CHANGE_PCT,
        )

        if fire and snap.status == STATUS_TRIGGER:
            self.tracker.mark_triggered(symbol, kline_close_time, snap.signal_type)
            alert = {
                "symbol": symbol,
                "type": snap.signal_type,
                "interval": self.interval,
                "signal_type": snap.signal_type,
                "supply_wall": snap.supply_wall,
                "anchor_level": snap.anchor_level,
                "anchor_kind": snap.anchor_kind,
                "last_price": float(klines[-1][4]),
                "message": snap.message,
                "oi_change_pct": self._oi_change_pct(symbol),
                "scan_ts": time.time(),
                "kline_close_time": kline_close_time,
            }
            logger.info("🎯 WS 扳机 %s %s", symbol, snap.message)
            if self.on_alert:
                self.on_alert(alert)
            return

        self.tracker.save_state(
            symbol,
            status=snap.status,
            signal_type=snap.signal_type,
            supply_wall=snap.supply_wall or state.get("supply_wall", 0.0),
            anchor_level=snap.anchor_level,
            anchor_kind=snap.anchor_kind,
            kline_close_time=kline_close_time,
            message=snap.message,
        )

    def _handle_open_interest(self, symbol: str, oi: float) -> None:
        now = time.time()
        self._oi_by_symbol[symbol] = oi
        self._oi_history.setdefault(symbol, deque(maxlen=60)).append((now, oi))

    async def process_market_data(self, payload: dict[str, Any]) -> None:
        """解析 combined stream 单条消息。"""
        data = payload.get("data") or payload
        event = data.get("e")
        if event == "kline":
            sym = str(data.get("s", "")).upper()
            kline = data.get("k") or {}
            await self._handle_kline_closed(sym, kline)
        elif event == "openInterest":
            sym = str(data.get("s", "")).upper()
            oi = float(data.get("o") or data.get("oi") or 0)
            self._handle_open_interest(sym, oi)

    async def start(self, *, reconnect_delay: float = 5.0) -> None:
        """连接 WS 并持续监听（自动重连）。"""
        if not self.symbols:
            raise ValueError("symbols 不能为空")

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(trust_env=True) as session:
            await self._bootstrap_klines(session)

        self._running = True
        url = self._ws_url()
        logger.info("🚀 WebSocket 连接 %s，监听 %d 个币种 (%s)", url, len(self.symbols), self.interval)

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await self.process_market_data(msg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("WS 断开，%ss 后重连: %s", reconnect_delay, exc)
                await asyncio.sleep(reconnect_delay)

    def stop(self) -> None:
        self._running = False
