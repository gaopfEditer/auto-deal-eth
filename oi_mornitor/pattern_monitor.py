"""形态监控引擎 — 自选 N 币 × 15m K 线 × 两步状态机。"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import aiohttp

from oi_mornitor.config import (
    FAPI_BASE_URL,
    HTTP_TIMEOUT_SEC,
    OI_OI_BATCH_CONCURRENCY,
    PATTERN_AUTO_PICK_COUNT,
    PATTERN_CHART_DEFAULT_LIMIT,
    PATTERN_CHART_MAX_LIMIT,
    PATTERN_KLINE_INTERVAL,
    PATTERN_KLINE_LIMIT,
)
from oi_mornitor.market_snapshot import TIER_HEAVY
from oi_mornitor.pattern_detector import (
    STATUS_LABELS,
    STATUS_LH,
    STATUS_SEARCHING,
    STATUS_TRIGGER,
    STATUS_WAITING,
    build_pattern_chart_payload,
    evaluate_pattern,
)
from oi_mornitor.pattern_state_tracker import PatternStateTracker

logger = logging.getLogger("OI_Radar")


async def fetch_pattern_klines(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    symbol: str,
    interval: str = PATTERN_KLINE_INTERVAL,
    limit: int = PATTERN_KLINE_LIMIT,
    end_time: int | None = None,
) -> list[list[Any]]:
    """拉取单币种 K 线；end_time 为毫秒时间戳，用于向左分页加载更早历史。"""
    sym = symbol.strip().upper()
    cap = min(max(limit, 1), PATTERN_CHART_MAX_LIMIT)
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    kline_url = f"{base_url.rstrip('/')}/fapi/v1/klines"
    url = f"{kline_url}?symbol={sym}&interval={interval}&limit={cap}"
    if end_time is not None and end_time > 0:
        url += f"&endTime={int(end_time)}"
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data if isinstance(data, list) else []
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError):
        return []


async def fetch_pattern_klines_batch(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    symbols: list[str],
    interval: str | None = None,
    limit: int | None = None,
) -> dict[str, list[list[Any]]]:
    interval = interval or PATTERN_KLINE_INTERVAL
    limit = limit if limit is not None else PATTERN_KLINE_LIMIT
    if not symbols:
        return {}

    sem = asyncio.Semaphore(OI_OI_BATCH_CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    out: dict[str, list[list[Any]]] = {}
    kline_url = f"{base_url.rstrip('/')}/fapi/v1/klines"

    async def _one(sym: str) -> None:
        url = f"{kline_url}?symbol={sym}&interval={interval}&limit={limit}"
        async with sem:
            try:
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status != 200:
                        out[sym] = []
                        return
                    data = await resp.json()
                    out[sym] = data if isinstance(data, list) else []
            except (asyncio.TimeoutError, aiohttp.ClientError, ValueError, TypeError):
                out[sym] = []

    await asyncio.gather(*[_one(s) for s in symbols])
    return out


def heavyweight_symbols(pool_rows: list[dict[str, Any]]) -> list[str]:
    """从雷达池提取大象级（heavyweight）币种。不按 warming 过滤——量级在首轮扫描即可确定。"""
    return [
        str(r["symbol"])
        for r in pool_rows
        if r.get("oi_tier") == TIER_HEAVY
    ]


def resolve_heavyweight_candidates(
    pool_rows: list[dict[str, Any]],
    *,
    fallback_symbols: list[str] | None = None,
) -> list[str]:
    candidates = heavyweight_symbols(pool_rows)
    if candidates:
        return candidates
    return list(fallback_symbols or [])


def pick_random_heavyweight(
    pool_rows: list[dict[str, Any]],
    *,
    count: int = PATTERN_AUTO_PICK_COUNT,
    exclude: set[str] | None = None,
    fallback_symbols: list[str] | None = None,
) -> list[str]:
    candidates = resolve_heavyweight_candidates(pool_rows, fallback_symbols=fallback_symbols)
    if exclude:
        candidates = [s for s in candidates if s not in exclude]
    if not candidates:
        return []
    if len(candidates) <= count:
        return candidates
    return random.sample(candidates, count)


class PatternMonitorEngine:
    def __init__(self) -> None:
        self.tracker = PatternStateTracker()
        self._last_alerts: list[dict[str, Any]] = []
        self._last_states: list[dict[str, Any]] = []
        self._last_scan_ts: float = 0.0
        self._last_pool_rows: list[dict[str, Any]] = []

    @property
    def last_alerts(self) -> list[dict[str, Any]]:
        return list(self._last_alerts)

    @property
    def last_states(self) -> list[dict[str, Any]]:
        return list(self._last_states)

    @property
    def last_scan_ts(self) -> float:
        return self._last_scan_ts

    def add_symbol(self, symbol: str) -> bool:
        return self.tracker.add_watch(symbol)

    def remove_symbol(self, symbol: str) -> bool:
        return self.tracker.remove_watch(symbol)

    def ensure_auto_watchlist(
        self,
        pool_rows: list[dict[str, Any]],
        *,
        fallback_symbols: list[str] | None = None,
    ) -> list[str]:
        """监听列表为空时，从大象池随机挑选默认数量。"""
        if self.tracker.list_watchlist():
            return []
        picked = pick_random_heavyweight(pool_rows, fallback_symbols=fallback_symbols)
        if not picked:
            return []
        self.tracker.replace_watchlist(picked)
        logger.info(
            "🎲 形态池自动初始化：大象随机 %d 个 → %s",
            len(picked),
            ", ".join(picked[:8]) + ("…" if len(picked) > 8 else ""),
        )
        return picked

    def random_pick_heavyweight(
        self,
        pool_rows: list[dict[str, Any]],
        *,
        fallback_symbols: list[str] | None = None,
    ) -> list[str]:
        """清空并重新从大象池随机挑选。"""
        picked = pick_random_heavyweight(pool_rows, fallback_symbols=fallback_symbols)
        if not picked:
            return []
        self.tracker.replace_watchlist(picked)
        logger.info(
            "🎲 形态池随机重选：大象 %d 个 → %s",
            len(picked),
            ", ".join(picked[:8]) + ("…" if len(picked) > 8 else ""),
        )
        return picked

    def get_watchlist(self) -> list[dict[str, Any]]:
        return [
            {"symbol": w.symbol, "interval": w.interval, "added_at": w.added_at}
            for w in self.tracker.list_watchlist()
        ]

    def get_payload(
        self,
        *,
        pool_meta: dict[str, Any] | None = None,
        fallback_symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        candidates = resolve_heavyweight_candidates(
            self._last_pool_rows,
            fallback_symbols=fallback_symbols,
        )
        heavy_count = len(candidates)
        if heavy_count == 0 and pool_meta:
            heavy_count = int(pool_meta.get("heavyweight_count") or 0)
        return {
            "scan_ts": self._last_scan_ts,
            "watchlist": self.get_watchlist(),
            "states": self._last_states,
            "pattern_alerts": self._last_alerts,
            "heavyweight_pool_size": heavy_count,
            "auto_pick_count": PATTERN_AUTO_PICK_COUNT,
        }

    async def scan(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = FAPI_BASE_URL,
        scan_ts: float | None = None,
        pool_rows: list[dict[str, Any]] | None = None,
        fallback_symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if pool_rows:
            self._last_pool_rows = pool_rows
            self.ensure_auto_watchlist(pool_rows, fallback_symbols=fallback_symbols)

        watchlist = self.tracker.list_watchlist()
        if not watchlist:
            self._last_alerts = []
            self._last_states = []
            self._last_scan_ts = scan_ts or time.time()
            return []

        self.tracker.expire_stale()
        symbols = [w.symbol for w in watchlist]
        klines_map = await fetch_pattern_klines_batch(
            session, base_url=base_url, symbols=symbols
        )

        alerts: list[dict[str, Any]] = []
        states: list[dict[str, Any]] = []

        for item in watchlist:
            sym = item.symbol
            klines = klines_map.get(sym) or []
            if not klines:
                states.append(self._state_dict(sym, item.interval, None))
                continue

            kline_close_time = int(klines[-1][6])
            row = self.tracker.get_state(sym)
            current_status = row.status if row else STATUS_SEARCHING
            state_data = {
                "h_max": row.h_max if row else 0.0,
                "lh_price": row.lh_price if row else 0.0,
                "l1": row.l1 if row else 0.0,
                "hl": row.hl if row else 0.0,
                "trigger_price": row.trigger_price if row else 0.0,
            }

            if row and row.trigger_emitted:
                states.append(self._state_dict(sym, item.interval, row))
                continue

            if row and kline_close_time <= row.last_kline_close_time:
                states.append(self._state_dict(sym, item.interval, row))
                continue

            snap, fire = evaluate_pattern(
                klines,
                current_status=current_status,
                state=state_data,
            )

            if snap.status == STATUS_LH and current_status in (STATUS_SEARCHING, ""):
                self.tracker.save_state(
                    sym,
                    status=snap.status,
                    h_max=snap.h_max,
                    lh_price=snap.lh_price,
                    kline_close_time=kline_close_time,
                    message=snap.message,
                )
                logger.info("📐 形态阶段1 %s LH=%.6f Hmax=%.6f", sym, snap.lh_price, snap.h_max)

            elif snap.status == STATUS_WAITING:
                self.tracker.save_state(
                    sym,
                    status=snap.status,
                    lh_price=snap.lh_price,
                    l1=snap.l1,
                    hl=snap.hl,
                    trigger_price=snap.trigger_price,
                    kline_close_time=kline_close_time,
                    message=snap.message,
                )

            elif snap.status == STATUS_TRIGGER and fire:
                self.tracker.mark_triggered(sym, kline_close_time)
                alert = {
                    "symbol": sym,
                    "type": "pattern_bull_continuation",
                    "interval": item.interval,
                    "status": STATUS_TRIGGER,
                    "status_label": STATUS_LABELS[STATUS_TRIGGER],
                    "lh_price": snap.lh_price,
                    "hl": snap.hl,
                    "trigger_price": snap.trigger_price,
                    "hh_price": snap.hh_price,
                    "last_price": float(klines[-1][4]),
                    "message": snap.message,
                    "scan_ts": scan_ts or time.time(),
                    "kline_close_time": kline_close_time,
                }
                alerts.append(alert)
                logger.info("🚀 形态扳机 %s 突破 %.6f", sym, snap.trigger_price)

            elif current_status not in (STATUS_SEARCHING,):
                self.tracker.save_state(
                    sym,
                    status=snap.status,
                    h_max=snap.h_max or state_data.get("h_max", 0.0),
                    lh_price=snap.lh_price or state_data.get("lh_price", 0.0),
                    l1=snap.l1 or state_data.get("l1", 0.0),
                    hl=snap.hl or state_data.get("hl", 0.0),
                    trigger_price=snap.trigger_price or state_data.get("trigger_price", 0.0),
                    hh_price=snap.hh_price,
                    kline_close_time=kline_close_time,
                    message=snap.message,
                )

            updated = self.tracker.get_state(sym)
            states.append(self._state_dict(sym, item.interval, updated))

        self._last_alerts = alerts
        self._last_states = states
        self._last_scan_ts = scan_ts or time.time()
        return alerts

    async def get_chart_data(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        *,
        base_url: str = FAPI_BASE_URL,
        pool_rows: list[dict[str, Any]] | None = None,
        interval: str | None = None,
        limit: int | None = None,
        end_time: int | None = None,
    ) -> dict[str, Any]:
        sym = symbol.strip().upper()
        tf = interval or PATTERN_KLINE_INTERVAL
        req_limit = limit if limit is not None else PATTERN_CHART_DEFAULT_LIMIT
        if end_time is None:
            req_limit = max(req_limit, PATTERN_CHART_DEFAULT_LIMIT)
        req_limit = min(req_limit, PATTERN_CHART_MAX_LIMIT)

        klines = await fetch_pattern_klines(
            session,
            base_url=base_url,
            symbol=sym,
            interval=tf,
            limit=req_limit,
            end_time=end_time,
        )

        partial = end_time is not None
        row = self.tracker.get_state(sym)
        state_dict: dict[str, Any] = {}
        if row and not partial:
            state_dict = {
                "status": row.status,
                "status_label": STATUS_LABELS.get(row.status, row.status),
                "h_max": row.h_max,
                "lh_price": row.lh_price,
                "l1": row.l1,
                "hl": row.hl,
                "trigger_price": row.trigger_price,
                "hh_price": row.hh_price,
                "message": row.message,
            }

        chart = build_pattern_chart_payload(klines, state=state_dict)

        if partial:
            return {
                "symbol": sym,
                "interval": tf,
                "partial": True,
                "candles": chart["candles"],
                "bb": chart["bb"],
                "vegas": chart.get("vegas") or {},
                "macd": chart.get("macd") or {"line": [], "signal": [], "hist": []},
                "has_more": len(klines) >= req_limit,
            }

        ticker: dict[str, Any] = {}
        if pool_rows:
            for r in pool_rows:
                if r.get("symbol") == sym:
                    ticker = {
                        "last_price": r.get("last_price"),
                        "price_change_pct_24h": r.get("price_change_pct_24h"),
                        "current_oi_usd": r.get("current_oi_usd"),
                        "quote_volume": r.get("quote_volume"),
                        "oi_tier": r.get("oi_tier"),
                    }
                    break

        if not ticker and chart["candles"]:
            last = chart["candles"][-1]
            ticker["last_price"] = last["close"]

        return {
            "symbol": sym,
            "interval": tf,
            "partial": False,
            "has_more": len(klines) >= req_limit,
            "ticker": ticker,
            "state": state_dict,
            **chart,
        }

    def _state_dict(
        self,
        symbol: str,
        interval: str,
        row: Any,
    ) -> dict[str, Any]:
        if row is None:
            return {
                "symbol": symbol,
                "interval": interval,
                "status": STATUS_SEARCHING,
                "status_label": STATUS_LABELS[STATUS_SEARCHING],
                "message": "等待 K 线",
            }
        return {
            "symbol": row.symbol,
            "interval": interval,
            "status": row.status,
            "status_label": STATUS_LABELS.get(row.status, row.status),
            "h_max": row.h_max,
            "lh_price": row.lh_price,
            "l1": row.l1,
            "hl": row.hl,
            "trigger_price": row.trigger_price,
            "hh_price": row.hh_price,
            "message": row.message,
            "updated_at": row.updated_at,
            "trigger_emitted": row.trigger_emitted,
        }
