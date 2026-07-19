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
    MATRIX_TOP_N,
    OI_OI_BATCH_CONCURRENCY,
    PATTERN_AUTO_PICK_COUNT,
    PATTERN_CHART_DEFAULT_LIMIT,
    PATTERN_CHART_MAX_LIMIT,
    PATTERN_KLINE_INTERVAL,
    PATTERN_KLINE_LIMIT,
    PATTERN_WATCHLIST_REFRESH_SEC,
    PATTERN_WATCHLIST_REFRESH_TF,
)
from oi_mornitor.exchange_sources import fetch_klines_with_fallback
from oi_mornitor.market_snapshot import TIER_HEAVY
from oi_mornitor.pattern_detector import (
    STATUS_EXPIRED,
    STATUS_LABELS,
    STATUS_LH,
    STATUS_SEARCHING,
    STATUS_TRIGGER,
    STATUS_WAITING,
    build_pattern_chart_payload,
    evaluate_pattern,
)
from oi_mornitor.pattern_state_tracker import MAX_WATCH_SYMBOLS, PatternStateTracker
from oi_mornitor.rank_metrics import TF_LABELS

logger = logging.getLogger("OI_Radar")

# 已进入形态阶段 / 已扳机：刷新 watchlist 时保留
_PROTECTED_PATTERN_STATUSES = frozenset({STATUS_LH, STATUS_WAITING, STATUS_TRIGGER})
# 涨幅∩持仓自动入池时，可被腾出的状态
_EVICTABLE_PATTERN_STATUSES = frozenset({STATUS_SEARCHING, STATUS_EXPIRED})


async def fetch_pattern_klines(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    symbol: str,
    interval: str = PATTERN_KLINE_INTERVAL,
    limit: int = PATTERN_KLINE_LIMIT,
    end_time: int | None = None,
) -> list[list[Any]]:
    """拉取单币种 K 线；币安 418/失败时自动走 Bybit/OKX 等备选所。"""
    sym = symbol.strip().upper()
    cap = min(max(limit, 1), PATTERN_CHART_MAX_LIMIT)
    rows, _src = await fetch_klines_with_fallback(
        session,
        symbol=sym,
        interval=interval,
        limit=cap,
        end_time=end_time,
        binance_base_url=base_url,
    )
    return rows


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
    out: dict[str, list[list[Any]]] = {}
    # 任一次币安失败后，后续批量请求跳过币安，避免 418 连打
    skip_binance = False

    async def _one(sym: str) -> None:
        nonlocal skip_binance
        async with sem:
            rows, src = await fetch_klines_with_fallback(
                session,
                symbol=sym,
                interval=interval,
                limit=limit,
                binance_base_url=base_url,
                skip_binance=skip_binance,
            )
            if src and src != "binance":
                skip_binance = True
            out[sym] = rows

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


def _rank_metric(row: dict[str, Any], tf: str, domain: str) -> dict[str, float]:
    return (row.get("rank_by_tf") or {}).get(tf, {}).get(domain) or {}


def _positive_magnitude(row: dict[str, Any], tf: str, domain: str) -> float:
    m = _rank_metric(row, tf, domain)
    rate = float(m.get("change_rate") or 0.0)
    mag = float(m.get("magnitude_usd") or 0.0)
    if rate <= 0 or mag <= 0:
        return 0.0
    return abs(mag)


def pick_hot_flow_and_oi(
    pool_rows: list[dict[str, Any]],
    *,
    count: int = PATTERN_AUTO_PICK_COUNT,
    tf: str = PATTERN_WATCHLIST_REFRESH_TF,
    exclude: set[str] | None = None,
    fallback_symbols: list[str] | None = None,
) -> list[str]:
    """从合约流入榜 + OI 爆发榜合并挑币；不足时回退大象池。"""
    exclude = {s.upper() for s in (exclude or set())}
    eligible = [
        r
        for r in pool_rows
        if r.get("status") != "warming"
        and str(r.get("symbol") or "").upper() not in exclude
    ]

    contract_ranked = sorted(
        eligible,
        key=lambda r: _positive_magnitude(r, tf, "contract_flow"),
        reverse=True,
    )
    oi_ranked = sorted(
        eligible,
        key=lambda r: _positive_magnitude(r, tf, "oi"),
        reverse=True,
    )

    out: list[str] = []
    seen: set[str] = set()
    half = max(1, (count + 1) // 2)

    def _take(rows: list[dict[str, Any]], domain: str, limit: int) -> None:
        for row in rows:
            if len(out) >= limit or len(out) >= count:
                return
            if _positive_magnitude(row, tf, domain) <= 0:
                continue
            sym = str(row.get("symbol") or "").upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append(sym)

    _take(contract_ranked, "contract_flow", half)
    _take(oi_ranked, "oi", count)
    if len(out) < count:
        _take(contract_ranked, "contract_flow", count)
    if len(out) < count:
        for sym in pick_random_heavyweight(
            pool_rows,
            count=count - len(out),
            exclude=seen | exclude,
            fallback_symbols=fallback_symbols,
        ):
            if sym not in seen:
                seen.add(sym)
                out.append(sym)

    return out[:count]


def _rank_score(row: dict[str, Any], tf: str, domain: str, *, mode: str) -> float:
    m = _rank_metric(row, tf, domain)
    rate = float(m.get("change_rate") or 0.0)
    if rate <= 0:
        return 0.0
    if mode == "intensity":
        return float(m.get("intensity_score") or 0.0)
    # 与前端 deriveLists 对齐：price 用量级=|rate|，oi 用 |magnitude_usd|
    if domain == "price":
        return abs(rate)
    return abs(float(m.get("magnitude_usd") or 0.0))


def _top_board_symbols(
    rows: list[dict[str, Any]],
    tf: str,
    domain: str,
    *,
    mode: str,
    top_n: int,
) -> list[str]:
    ranked = sorted(
        rows,
        key=lambda r: _rank_score(r, tf, domain, mode=mode),
        reverse=True,
    )
    out: list[str] = []
    for row in ranked:
        if _rank_score(row, tf, domain, mode=mode) <= 0:
            continue
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        out.append(sym)
        if len(out) >= top_n:
            break
    return out


def find_gainers_oi_intersection(
    pool_rows: list[dict[str, Any]],
    *,
    top_n: int = MATRIX_TOP_N,
    timeframes: tuple[str, ...] = TF_LABELS,
) -> list[str]:
    """
    雷达涨幅榜 ∩ 持仓正榜（量级或强度任一上榜即计入）。
    任一周期命中即纳入；返回去重后的 symbol 列表。
    """
    eligible = [r for r in pool_rows if r.get("status") != "warming"]
    hits: list[str] = []
    seen: set[str] = set()
    for tf in timeframes:
        gainers = set(_top_board_symbols(eligible, tf, "price", mode="mag", top_n=top_n)) | set(
            _top_board_symbols(eligible, tf, "price", mode="intensity", top_n=top_n)
        )
        oi_pos = set(_top_board_symbols(eligible, tf, "oi", mode="mag", top_n=top_n)) | set(
            _top_board_symbols(eligible, tf, "oi", mode="intensity", top_n=top_n)
        )
        for sym in gainers & oi_pos:
            if sym not in seen:
                seen.add(sym)
                hits.append(sym)
    return hits


class PatternMonitorEngine:
    def __init__(self) -> None:
        self.tracker = PatternStateTracker()
        self._last_alerts: list[dict[str, Any]] = []
        self._last_states: list[dict[str, Any]] = []
        self._last_scan_ts: float = 0.0
        self._last_pool_rows: list[dict[str, Any]] = []
        self._last_watchlist_refresh_ts: float = 0.0

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

    def pin_symbol_to_top(self, symbol: str) -> bool:
        """手动置顶至少一天（兼容旧 API 名）。"""
        return self.tracker.pin_watch(symbol)

    def unpin_symbol(self, symbol: str) -> bool:
        return self.tracker.unpin_watch(symbol)

    def ensure_auto_watchlist(
        self,
        pool_rows: list[dict[str, Any]],
        *,
        fallback_symbols: list[str] | None = None,
    ) -> list[str]:
        """监听列表为空时，优先合约流入 + OI 爆发，不足再补大象池。"""
        if self.tracker.list_watchlist():
            return []
        picked = pick_hot_flow_and_oi(pool_rows, fallback_symbols=fallback_symbols)
        if not picked:
            return []
        self.tracker.replace_watchlist(picked)
        self._last_watchlist_refresh_ts = time.time()
        logger.info(
            "🎲 形态池自动初始化：流入/OI %d 个 → %s",
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
        """清空并重新从合约流入 + OI 爆发挑币（不足补大象）。"""
        picked = pick_hot_flow_and_oi(pool_rows, fallback_symbols=fallback_symbols)
        if not picked:
            return []
        self.tracker.replace_watchlist(picked)
        self._last_watchlist_refresh_ts = time.time()
        logger.info(
            "🎲 形态池热钱重选：流入/OI %d 个 → %s",
            len(picked),
            ", ".join(picked[:8]) + ("…" if len(picked) > 8 else ""),
        )
        return picked

    def _protected_symbols(self, protect_extra: set[str] | None = None) -> set[str]:
        protected = {s.upper() for s in (protect_extra or set())}
        for st in self.tracker.list_states():
            if st.status in _PROTECTED_PATTERN_STATUSES:
                protected.add(st.symbol.upper())
        for w in self.tracker.list_watchlist():
            if w.is_pinned:
                protected.add(w.symbol.upper())
        return protected

    def refresh_watchlist_from_hot(
        self,
        pool_rows: list[dict[str, Any]],
        *,
        fallback_symbols: list[str] | None = None,
        protect_extra: set[str] | None = None,
        force: bool = False,
    ) -> list[str]:
        """
        每隔 PATTERN_WATCHLIST_REFRESH_SEC，用合约流入榜 + OI 爆发榜更新形态列表。
        已进入 LH/等待 HL/扳机 的币，以及 protect_extra（如沙盒持仓）保留；其余可被替换。
        """
        now = time.time()
        if not force and self._last_watchlist_refresh_ts > 0:
            if now - self._last_watchlist_refresh_ts < PATTERN_WATCHLIST_REFRESH_SEC:
                return []

        current = [w.symbol.upper() for w in self.tracker.list_watchlist()]
        protected = self._protected_symbols(protect_extra)
        # 只保护仍在 watchlist 内的
        protected &= set(current)

        hot = pick_hot_flow_and_oi(
            pool_rows,
            count=PATTERN_AUTO_PICK_COUNT,
            fallback_symbols=fallback_symbols,
        )
        if not hot and not protected:
            self._last_watchlist_refresh_ts = now
            return []

        target: list[str] = []
        seen: set[str] = set()
        for sym in protected:
            if sym not in seen:
                seen.add(sym)
                target.append(sym)
        for sym in hot:
            if len(target) >= PATTERN_AUTO_PICK_COUNT:
                break
            if sym in seen:
                continue
            seen.add(sym)
            target.append(sym)

        # 槽位未满时保留仍在列表中的未进场币（稳定过渡）
        if len(target) < PATTERN_AUTO_PICK_COUNT:
            for sym in current:
                if len(target) >= PATTERN_AUTO_PICK_COUNT:
                    break
                if sym in seen:
                    continue
                seen.add(sym)
                target.append(sym)

        target = target[:MAX_WATCH_SYMBOLS]
        current_set = set(current)
        target_set = set(target)
        to_remove = current_set - target_set - protected
        to_add = [s for s in target if s not in current_set]

        if not to_remove and not to_add:
            self._last_watchlist_refresh_ts = now
            return []

        for sym in to_remove:
            self.tracker.remove_watch(sym)
        for sym in to_add:
            self.tracker.add_watch(sym)

        self._last_watchlist_refresh_ts = now
        logger.info(
            "🔄 形态池热钱刷新：保留已进场 %d · 移除 %d · 新增 %d → %s",
            len(protected),
            len(to_remove),
            len(to_add),
            ", ".join(target[:8]) + ("…" if len(target) > 8 else ""),
        )
        return target

    def _evict_one_replaceable(self, protect_extra: set[str] | None = None) -> str | None:
        """腾出一个未进场槽位；优先 EXPIRED，再 SEARCHING（按 added_at 最旧）。"""
        protected = self._protected_symbols(protect_extra)
        watch = self.tracker.list_watchlist()
        states = {s.symbol.upper(): s for s in self.tracker.list_states()}
        candidates: list[tuple[int, float, str]] = []
        for w in watch:
            sym = w.symbol.upper()
            if sym in protected:
                continue
            st = states.get(sym)
            status = st.status if st else STATUS_SEARCHING
            if status not in _EVICTABLE_PATTERN_STATUSES:
                continue
            # EXPIRED 优先踢出
            prio = 0 if status == STATUS_EXPIRED else 1
            candidates.append((prio, w.added_at, sym))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        victim = candidates[0][2]
        self.tracker.remove_watch(victim)
        return victim

    def ingest_gainers_oi_intersection(
        self,
        pool_rows: list[dict[str, Any]],
        *,
        protect_extra: set[str] | None = None,
    ) -> list[str]:
        """
        雷达涨幅榜 ∩ 持仓正榜 → 自动加入形态追踪。
        列表已满时踢掉未进场币腾位；新币置顶便于看到。
        """
        hits = find_gainers_oi_intersection(pool_rows)
        if not hits:
            return []

        current = {w.symbol.upper() for w in self.tracker.list_watchlist()}
        added: list[str] = []
        for sym in hits:
            if sym in current:
                continue
            while len(current) >= MAX_WATCH_SYMBOLS:
                victim = self._evict_one_replaceable(protect_extra)
                if not victim:
                    break
                current.discard(victim)
            if len(current) >= MAX_WATCH_SYMBOLS:
                logger.info(
                    "涨幅∩持仓 %s 未能入池：形态列表已满且无可替换币",
                    sym,
                )
                break
            if self.tracker.add_watch(sym):
                current.add(sym)
                self.tracker.bump_watch_to_top(sym)
                added.append(sym)

        if added:
            logger.info(
                "📈 涨幅∩持仓 → 形态追踪 +%d：%s",
                len(added),
                ", ".join(added),
            )
        return added

    def get_watchlist(self) -> list[dict[str, Any]]:
        now = time.time()
        return [
            {
                "symbol": w.symbol,
                "interval": w.interval,
                "added_at": w.added_at,
                "pinned": w.is_pinned,
                "pinned_until": w.pinned_until if w.is_pinned else 0,
                "pin_remaining_sec": max(0, int(w.pinned_until - now)) if w.is_pinned else 0,
            }
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
            "watchlist_refresh_sec": PATTERN_WATCHLIST_REFRESH_SEC,
            "watchlist_refresh_tf": PATTERN_WATCHLIST_REFRESH_TF,
            "last_watchlist_refresh_ts": self._last_watchlist_refresh_ts,
        }

    async def scan(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = FAPI_BASE_URL,
        scan_ts: float | None = None,
        pool_rows: list[dict[str, Any]] | None = None,
        fallback_symbols: list[str] | None = None,
        protect_symbols: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if pool_rows:
            self._last_pool_rows = pool_rows
            self.tracker.expire_pins()
            self.ensure_auto_watchlist(pool_rows, fallback_symbols=fallback_symbols)
            self.refresh_watchlist_from_hot(
                pool_rows,
                fallback_symbols=fallback_symbols,
                protect_extra=protect_symbols,
            )
            # 每轮扫描：涨幅榜 ∩ 持仓正榜 → 立即加入形态追踪
            self.ingest_gainers_oi_intersection(
                pool_rows,
                protect_extra=protect_symbols,
            )

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
