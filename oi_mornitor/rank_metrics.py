"""
排行榜衍生字段：magnitude_usd（量级）与 intensity_score（强度分）。

- magnitude_usd：OI 持仓变动 abs(ΔOI)×价格；主力大单为 Taker 净流（买−卖）。
- intensity_score：15m 变动率相对 24h 历史的 pandas Z-Score，扫描批次内归一化至 0–100。
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from oi_mornitor.config import OI_ZSCORE_MIN_SAMPLES

# 与 radar.OI_TF_WINDOWS 对齐
TF_LABELS: tuple[str, ...] = ("15m", "30m", "1h", "4h", "1d")

DOMAINS: tuple[str, ...] = ("price", "oi", "contract_flow", "spot_flow")

# 24h × 每 15m 采样 ≈ 96 个变动率样本
CHANGE_RATE_HISTORY_LEN = 96
CHANGE_RATE_RECORD_SEC = 900


def _empty_metric() -> dict[str, float]:
    return {
        "magnitude_usd": 0.0,
        "change_rate": 0.0,
        "z_score": 0.0,
        "intensity_score": 0.0,
    }


def empty_rank_by_tf() -> dict[str, dict[str, dict[str, float]]]:
    return {tf: {d: _empty_metric() for d in DOMAINS} for tf in TF_LABELS}


def _calc_change_rate(current: float, past: float) -> float:
    if past <= 0:
        return 0.0
    return (current - past) / past


def _z_score_pandas(history: list[float], current: float) -> float:
    if len(history) < OI_ZSCORE_MIN_SAMPLES:
        return 0.0
    series = pd.Series(history, dtype=float)
    std = float(series.std(ddof=0))
    if std < 1e-12:
        return 0.0
    return float((current - series.mean()) / std)


def _normalize_intensity_batch(z_by_symbol: dict[str, float]) -> dict[str, float]:
    if not z_by_symbol:
        return {}
    max_abs = max(abs(z) for z in z_by_symbol.values())
    if max_abs < 1e-12:
        return {sym: 0.0 for sym in z_by_symbol}
    return {
        sym: round(abs(z) / max_abs * 100.0, 1)
        for sym, z in z_by_symbol.items()
    }


@dataclass
class ChangeRateHistory:
    """每币种 × 维度 × 周期缓存 24h 变动率，供 Z-Score。"""

    maxlen: int = CHANGE_RATE_HISTORY_LEN
    record_interval_sec: int = CHANGE_RATE_RECORD_SEC
    _history: dict[str, deque[float]] = field(default_factory=dict)
    _last_record_ts: dict[str, float] = field(default_factory=dict)

    def _key(self, symbol: str, domain: str, tf: str) -> str:
        return f"{symbol}:{domain}:{tf}"

    def z_score_and_maybe_record(
        self,
        symbol: str,
        domain: str,
        tf: str,
        change_rate: float,
    ) -> float:
        key = self._key(symbol, domain, tf)
        hist = self._history.get(key)
        z = _z_score_pandas(list(hist) if hist else [], change_rate)

        now = time.time()
        last = self._last_record_ts.get(key, 0.0)
        if key not in self._history:
            self._history[key] = deque(maxlen=self.maxlen)
        if now - last >= self.record_interval_sec:
            self._history[key].append(change_rate)
            self._last_record_ts[key] = now
        return z


@dataclass
class RankMetricsEngine:
    """扫描批次内计算 rank_by_tf 并写入每行。"""

    history: ChangeRateHistory = field(default_factory=ChangeRateHistory)

    def _raw_metrics(
        self,
        row: dict[str, Any],
        tf: str,
    ) -> dict[str, dict[str, float]]:
        oi_win = row.get("oi_by_tf", {}).get(tf, {})
        price_win = row.get("price_by_tf", {}).get(tf, {})
        flow_win = row.get("flow_by_tf", {}).get(tf, {})
        spot_win = row.get("spot_flow_by_tf", {}).get(tf, {})

        oi_delta_usd = float(oi_win.get("delta_usd", 0.0))
        oi_pct = float(oi_win.get("pct", 0.0))
        price_pct = float(price_win.get("pct", 0.0))
        contract_net = float(flow_win.get("net_usd", 0.0))
        contract_vol = float(flow_win.get("volume_usd", 0.0))
        spot_net = float(spot_win.get("net_usd", 0.0))
        spot_vol = float(spot_win.get("volume_usd", 0.0))
        oi_usd = float(row.get("current_oi_usd", 0.0))

        oi_change_rate = oi_pct / 100.0
        price_change_rate = price_pct / 100.0
        contract_change_rate = (
            contract_net / contract_vol if contract_vol > 1e-9 else 0.0
        )
        spot_change_rate = spot_net / spot_vol if spot_vol > 1e-9 else 0.0

        return {
            "oi": {
                "magnitude_usd": abs(oi_delta_usd),
                "change_rate": oi_change_rate,
            },
            "price": {
                "magnitude_usd": abs(price_change_rate) * oi_usd,
                "change_rate": price_change_rate,
            },
            "contract_flow": {
                "magnitude_usd": contract_net,
                "change_rate": contract_change_rate,
            },
            "spot_flow": {
                "magnitude_usd": spot_net,
                "change_rate": spot_change_rate,
            },
        }

    def enrich(self, rows: list[dict[str, Any]]) -> None:
        eligible = [r for r in rows if r.get("status") != "warming"]
        if not eligible:
            for row in rows:
                row["rank_by_tf"] = empty_rank_by_tf()
            return

        # 第一遍：原始量级 + 变动率 + 单币 Z-Score
        z_buckets: dict[tuple[str, str], dict[str, float]] = {
            (tf, domain): {} for tf in TF_LABELS for domain in DOMAINS
        }

        for row in eligible:
            sym = row["symbol"]
            rank_by_tf: dict[str, dict[str, dict[str, float]]] = {}
            for tf in TF_LABELS:
                raw = self._raw_metrics(row, tf)
                rank_by_tf[tf] = {}
                for domain in DOMAINS:
                    mag = raw[domain]["magnitude_usd"]
                    rate = raw[domain]["change_rate"]
                    z = self.history.z_score_and_maybe_record(sym, domain, tf, rate)
                    rank_by_tf[tf][domain] = {
                        "magnitude_usd": round(mag, 2),
                        "change_rate": round(rate, 6),
                        "z_score": round(z, 4),
                        "intensity_score": 0.0,
                    }
                    z_buckets[(tf, domain)][sym] = z
            row["rank_by_tf"] = rank_by_tf

        # 第二遍：批次内 Z-Score → 0–100 强度分
        for tf in TF_LABELS:
            for domain in DOMAINS:
                intensity_map = _normalize_intensity_batch(z_buckets[(tf, domain)])
                for row in eligible:
                    sym = row["symbol"]
                    row["rank_by_tf"][tf][domain]["intensity_score"] = intensity_map.get(
                        sym, 0.0
                    )

        for row in rows:
            if row.get("status") == "warming":
                row["rank_by_tf"] = empty_rank_by_tf()
