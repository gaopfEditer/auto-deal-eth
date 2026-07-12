"""
榜单币种突破扫描：收集矩阵 Top 币 → 拉 5m OHLC → 两步状态机 → 扳机告警。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from oi_mornitor.breakout_detector import (
    is_pullback_trigger,
    is_valid_breakout,
    klines_to_df,
)
from oi_mornitor.config import (
    BREAKOUT_KLINE_LIMIT,
    BREAKOUT_LOOKBACK,
    BREAKOUT_MATRIX_TF,
    FAPI_BASE_URL,
    HTTP_TIMEOUT_SEC,
    MATRIX_TOP_N,
    OI_OI_BATCH_CONCURRENCY,
)
from oi_mornitor.rank_metrics import DOMAINS
from oi_mornitor.state_tracker import BreakoutStateTracker

logger = logging.getLogger("OI_Radar")

# 与前端 deriveLists 榜单 category 对齐
_MAGNITUDE_DOMAINS = {
    "price": ("gainers_magnitude", "losers_magnitude"),
    "oi": ("oi_pumps", "oi_dumps"),
    "contract_flow": ("contract_inflow", "contract_outflow"),
    "spot_flow": ("spot_inflow", "spot_outflow"),
}
_STRENGTH_DOMAINS = {
    "price": ("gainers_strength", "losers_strength"),
    "oi": ("oi_pump_strength", "oi_dump_strength"),
    "contract_flow": ("contract_inflow_strength", "contract_outflow_strength"),
    "spot_flow": ("spot_inflow_strength", "spot_outflow_strength"),
}

_CATEGORY_LABELS: dict[str, str] = {
    "gainers_magnitude": "涨幅·量级",
    "losers_magnitude": "跌幅·量级",
    "gainers_strength": "涨幅·强度",
    "losers_strength": "跌幅·强度",
    "oi_pumps": "持仓·正·量级",
    "oi_dumps": "持仓·负·量级",
    "oi_pump_strength": "持仓·正·强度",
    "oi_dump_strength": "持仓·负·强度",
    "contract_inflow": "合约·流入·量级",
    "contract_outflow": "合约·流出·量级",
    "contract_inflow_strength": "合约·流入·强度",
    "contract_outflow_strength": "合约·流出·强度",
    "spot_inflow": "现货·流入·量级",
    "spot_outflow": "现货·流出·量级",
    "spot_inflow_strength": "现货·流入·强度",
    "spot_outflow_strength": "现货·流出·强度",
}


def _eligible(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("status") != "warming"]


def _rank_metric(row: dict[str, Any], tf: str, domain: str) -> dict[str, float]:
    rank_by_tf = row.get("rank_by_tf") or {}
    tf_block = rank_by_tf.get(tf) or {}
    metric = tf_block.get(domain) or {}
    return {
        "magnitude_usd": float(metric.get("magnitude_usd") or 0.0),
        "change_rate": float(metric.get("change_rate") or 0.0),
        "intensity_score": float(metric.get("intensity_score") or 0.0),
    }


def _pick_magnitude(
    rows: list[dict[str, Any]],
    tf: str,
    domain: str,
    category: str,
    positive: bool,
    top_n: int,
) -> list[tuple[str, str, int]]:
    picked = [
        r
        for r in _eligible(rows)
        if (_rank_metric(r, tf, domain)["change_rate"] > 0 if positive else _rank_metric(r, tf, domain)["change_rate"] < 0)
    ]
    picked.sort(
        key=lambda r: abs(_rank_metric(r, tf, domain)["magnitude_usd"]),
        reverse=True,
    )
    return [(r["symbol"], category, i + 1) for i, r in enumerate(picked[:top_n])]


def _pick_strength(
    rows: list[dict[str, Any]],
    tf: str,
    domain: str,
    category: str,
    positive: bool,
    top_n: int,
) -> list[tuple[str, str, int]]:
    picked = [
        r
        for r in _eligible(rows)
        if (_rank_metric(r, tf, domain)["change_rate"] > 0 if positive else _rank_metric(r, tf, domain)["change_rate"] < 0)
    ]
    picked.sort(
        key=lambda r: _rank_metric(r, tf, domain)["intensity_score"],
        reverse=True,
    )
    return [(r["symbol"], category, i + 1) for i, r in enumerate(picked[:top_n])]


def collect_matrix_leaderboard(
    rows: list[dict[str, Any]],
    *,
    tf: str = BREAKOUT_MATRIX_TF,
    top_n: int = MATRIX_TOP_N,
) -> dict[str, dict[str, Any]]:
    """
    收集当前矩阵 16 榜 Top 币种。
    返回 {symbol: {categories: [...], best_rank, labels}}。
    """
    entries: list[tuple[str, str, int]] = []
    for domain in DOMAINS:
        pos_cat, neg_cat = _MAGNITUDE_DOMAINS[domain]
        entries.extend(_pick_magnitude(rows, tf, domain, pos_cat, True, top_n))
        entries.extend(_pick_magnitude(rows, tf, domain, neg_cat, False, top_n))
        pos_s, neg_s = _STRENGTH_DOMAINS[domain]
        entries.extend(_pick_strength(rows, tf, domain, pos_s, True, top_n))
        entries.extend(_pick_strength(rows, tf, domain, neg_s, False, top_n))

    out: dict[str, dict[str, Any]] = {}
    for symbol, category, rank in entries:
        bucket = out.setdefault(
            symbol,
            {"categories": [], "best_rank": rank, "labels": []},
        )
        if category not in bucket["categories"]:
            bucket["categories"].append(category)
            bucket["labels"].append(_CATEGORY_LABELS.get(category, category))
        bucket["best_rank"] = min(bucket["best_rank"], rank)

    return out


async def fetch_ohlc_klines_batch(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    symbols: list[str],
) -> dict[str, list[list[Any]]]:
    if not symbols:
        return {}

    sem = asyncio.Semaphore(OI_OI_BATCH_CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SEC)
    out: dict[str, list[list[Any]]] = {}
    kline_url = f"{base_url.rstrip('/')}/fapi/v1/klines"

    async def _one(sym: str) -> None:
        url = f"{kline_url}?symbol={sym}&interval=5m&limit={BREAKOUT_KLINE_LIMIT}"
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


def _row_by_symbol(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["symbol"]: r for r in rows}


class MatrixBreakoutEngine:
    def __init__(self) -> None:
        self.tracker = BreakoutStateTracker()
        self._last_alerts: list[dict[str, Any]] = []

    @property
    def last_alerts(self) -> list[dict[str, Any]]:
        return list(self._last_alerts)

    async def scan(
        self,
        session: aiohttp.ClientSession,
        rows: list[dict[str, Any]],
        *,
        base_url: str = FAPI_BASE_URL,
        scan_ts: float,
        tf: str = BREAKOUT_MATRIX_TF,
    ) -> list[dict[str, Any]]:
        leaderboard = collect_matrix_leaderboard(rows, tf=tf)
        if not leaderboard:
            self._last_alerts = []
            return []

        self.tracker.expire_stale()

        # 榜单币 + 已在观察中的币
        watch_symbols = set(leaderboard.keys())
        for state in self.tracker.list_watching():
            watch_symbols.add(state.symbol)

        klines_map = await fetch_ohlc_klines_batch(
            session, base_url=base_url, symbols=sorted(watch_symbols)
        )
        row_map = _row_by_symbol(rows)
        alerts: list[dict[str, Any]] = []

        # 第一步：榜单币检测新突破（仅涨幅方向榜单中的正向变动币）
        for symbol, meta in leaderboard.items():
            klines = klines_map.get(symbol) or []
            if len(klines) < BREAKOUT_LOOKBACK + 1:
                continue
            df = klines_to_df(klines)
            ok, supply_wall = is_valid_breakout(df)
            if not ok:
                continue
            kline_close_time = int(klines[-1][6])
            categories = ",".join(meta["categories"])
            self.tracker.upsert_detected(
                symbol,
                supply_wall,
                categories,
                kline_close_time,
            )
            logger.info(
                "📍 突破蓄势 %s supply_wall=%.6f [%s]",
                symbol,
                supply_wall,
                categories,
            )

        # 第二步：观察中的币检测回踩扳机
        for state in self.tracker.list_watching():
            klines = klines_map.get(state.symbol) or []
            if len(klines) < BREAKOUT_LOOKBACK + 1:
                continue
            kline_close_time = int(klines[-1][6])
            if kline_close_time <= state.last_kline_close_time:
                continue

            df = klines_to_df(klines)
            if not is_pullback_trigger(df, state.supply_wall):
                continue

            self.tracker.mark_triggered(state.symbol, kline_close_time)
            row = row_map.get(state.symbol) or {}
            labels = [
                _CATEGORY_LABELS.get(c.strip(), c.strip())
                for c in state.categories.split(",")
                if c.strip()
            ]
            alert = {
                "symbol": state.symbol,
                "type": "breakout_trigger",
                "supply_wall": state.supply_wall,
                "last_price": float(row.get("last_price") or klines[-1][4]),
                "categories": state.categories,
                "category_labels": labels,
                "matrix_tf": tf,
                "scan_ts": scan_ts,
                "kline_close_time": kline_close_time,
                "message": f"回踩供给墙 ${state.supply_wall:.4g} · 缩量确认",
            }
            alerts.append(alert)
            logger.info(
                "🎯 扳机信号 %s @ wall=%.6f [%s]",
                state.symbol,
                state.supply_wall,
                state.categories,
            )

        self._last_alerts = alerts
        return alerts
