"""
热钱四宫格聚合分类器 — 基于雷达扫描快照输出四个子榜单。

核心入口：
    from oi_mornitor import get_market_matrix
    matrix = await get_market_matrix()
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from oi_mornitor.config import MATRIX_REFRESH_SEC, MATRIX_TOP_N


def _pump_score(row: dict[str, Any]) -> float:
    """5m/15m 正向 OI 变动绝对值（取更强窗口）。"""
    return max(row.get("delta_5m_usd", 0.0), row.get("delta_15m_usd", 0.0))


def _dump_score(row: dict[str, Any]) -> float:
    """5m/15m 负向 OI 变动绝对值（取更强窗口，返回负数便于排序）。"""
    return min(row.get("delta_5m_usd", 0.0), row.get("delta_15m_usd", 0.0))


def _slim_row(row: dict[str, Any], *, rank: int, score: float, category: str) -> dict[str, Any]:
    return {
        "symbol": row["symbol"],
        "category": category,
        "matrix_rank": rank,
        "matrix_score": round(score, 4),
        "last_price": row.get("last_price"),
        "price_change_pct_24h": row.get("price_change_pct_24h", 0.0),
        "quote_volume": row.get("quote_volume", 0.0),
        "volume_rank": row.get("volume_rank"),
        "current_oi_usd": row.get("current_oi_usd", 0.0),
        "delta_5m_usd": row.get("delta_5m_usd", 0.0),
        "pct_5m": row.get("pct_5m", 0.0),
        "delta_15m_usd": row.get("delta_15m_usd", 0.0),
        "pct_15m": row.get("pct_15m", 0.0),
        "global_intensity_rank": row.get("global_intensity_rank"),
        "global_volume_rank": row.get("global_volume_rank"),
    }


def build_market_matrix(
    rows: list[dict[str, Any]],
    *,
    top_n: int = MATRIX_TOP_N,
    scan_ts: float = 0.0,
) -> dict[str, Any]:
    """
    将雷达全量行聚合为四个子榜单。

    - top_gainers_oi: 24h 涨幅前 N 且 5m OI 正向增加
    - top_losers_oi: 24h 跌幅前 N 且 5m OI 负向减少
    - oi_pumps: 5m/15m OI 暴增绝对值前 N（不看价格方向）
    - oi_dumps: 5m/15m OI 暴跌绝对值前 N（不看价格方向）
    """
    eligible = [r for r in rows if r.get("status") != "warming"]
    now = time.time()

    gainers_src = [r for r in eligible if r.get("delta_5m_usd", 0.0) > 0]
    gainers_src.sort(key=lambda r: r.get("price_change_pct_24h", 0.0), reverse=True)
    top_gainers_oi = [
        _slim_row(r, rank=i, score=r.get("price_change_pct_24h", 0.0), category="top_gainers_oi")
        for i, r in enumerate(gainers_src[:top_n], start=1)
    ]

    losers_src = [r for r in eligible if r.get("delta_5m_usd", 0.0) < 0]
    losers_src.sort(key=lambda r: r.get("price_change_pct_24h", 0.0))
    top_losers_oi = [
        _slim_row(r, rank=i, score=r.get("price_change_pct_24h", 0.0), category="top_losers_oi")
        for i, r in enumerate(losers_src[:top_n], start=1)
    ]

    pumps_src = [r for r in eligible if _pump_score(r) > 0]
    pumps_src.sort(key=_pump_score, reverse=True)
    oi_pumps = [
        _slim_row(r, rank=i, score=_pump_score(r), category="oi_pumps")
        for i, r in enumerate(pumps_src[:top_n], start=1)
    ]

    dumps_src = [r for r in eligible if _dump_score(r) < 0]
    dumps_src.sort(key=_dump_score)
    oi_dumps = [
        _slim_row(r, rank=i, score=abs(_dump_score(r)), category="oi_dumps")
        for i, r in enumerate(dumps_src[:top_n], start=1)
    ]

    return {
        "matrix_ts": now,
        "scan_ts": scan_ts,
        "top_n": top_n,
        "refresh_sec": MATRIX_REFRESH_SEC,
        "pool_eligible": len(eligible),
        "top_gainers_oi": top_gainers_oi,
        "top_losers_oi": top_losers_oi,
        "oi_pumps": oi_pumps,
        "oi_dumps": oi_dumps,
    }


class MarketMatrixCache:
    """基于雷达快照的矩阵缓存，默认每 60s 刷新。"""

    def __init__(self) -> None:
        self._matrix: dict[str, Any] = build_market_matrix([])
        self._matrix_ts: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def last_matrix(self) -> dict[str, Any]:
        return dict(self._matrix)

    def update_from_rows(self, rows: list[dict[str, Any]], *, scan_ts: float) -> dict[str, Any]:
        self._matrix = build_market_matrix(rows, scan_ts=scan_ts)
        self._matrix_ts = self._matrix["matrix_ts"]
        return self._matrix

    async def get(
        self,
        rows: list[dict[str, Any]],
        *,
        scan_ts: float,
        force: bool = False,
    ) -> dict[str, Any]:
        async with self._lock:
            stale = time.time() - self._matrix_ts >= MATRIX_REFRESH_SEC
            if force or stale or not rows:
                if rows:
                    return self.update_from_rows(rows, scan_ts=scan_ts)
            return dict(self._matrix)
