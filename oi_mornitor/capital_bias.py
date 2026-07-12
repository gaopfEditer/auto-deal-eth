"""
资金倾向性 Top N — 合流（现货+合约同向/反转接盘）与力度（净流强度）。
"""
from __future__ import annotations

from typing import Any

from oi_mornitor.config import MATRIX_TOP_N

CAPITAL_BIAS_TF = "15m"


def _fmt_score(n: float, digits: int = 2) -> str:
    abs_n = abs(n)
    if abs_n >= 1e9:
        return f"{abs_n / 1e9:.{digits}f}B"
    return f"{abs_n / 1e6:.{digits}f}M"


def _win(row: dict[str, Any], key: str, tf: str) -> dict[str, float]:
    return row.get(key, {}).get(tf, {"net_usd": 0.0, "volume_usd": 0.0})


def _oi_win(row: dict[str, Any], tf: str) -> dict[str, float]:
    return row.get("oi_by_tf", {}).get(tf, {"delta_usd": 0.0, "pct": 0.0})


def _slim_bias_item(
    row: dict[str, Any],
    *,
    rank: int,
    score: float,
    direction: str,
) -> dict[str, Any]:
    label = "流入" if direction == "inflow" else "流出"
    return {
        "symbol": row["symbol"],
        "rank": rank,
        "direction": direction,
        "direction_label": label,
        "score": round(score, 2),
        "score_fmt": _fmt_score(score),
    }


def build_capital_confluence(
    rows: list[dict[str, Any]],
    *,
    tf: str = CAPITAL_BIAS_TF,
    top_n: int = MATRIX_TOP_N,
) -> list[dict[str, Any]]:
    """
    资金合流：现货+合约 Taker 同向合流；或 OI 减仓 + 现货流入（空头爆仓接盘）。
    """
    eligible = [r for r in rows if r.get("status") != "warming"]
    scored: list[tuple[dict[str, Any], float, str]] = []

    for row in eligible:
        contract = _win(row, "flow_by_tf", tf)["net_usd"]
        spot = _win(row, "spot_flow_by_tf", tf)["net_usd"]
        oi_delta = _oi_win(row, tf)["delta_usd"]

        score = 0.0
        direction = "inflow"

        if contract * spot > 0:
            score = min(abs(contract), abs(spot))
            direction = "inflow" if contract > 0 else "outflow"

        if oi_delta < 0 and spot > 0:
            rev = abs(spot) + (abs(contract) * 0.5 if contract < 0 else 0.0)
            if rev > score:
                score = rev
                direction = "inflow"
        elif oi_delta > 0 and spot < 0:
            rev = abs(spot) + (abs(contract) * 0.5 if contract > 0 else 0.0)
            if rev > score:
                score = rev
                direction = "outflow"

        if score > 0:
            scored.append((row, score, direction))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [
        _slim_bias_item(row, rank=i, score=score, direction=direction)
        for i, (row, score, direction) in enumerate(scored[:top_n], start=1)
    ]


def build_capital_intensity(
    rows: list[dict[str, Any]],
    *,
    tf: str = CAPITAL_BIAS_TF,
    top_n: int = MATRIX_TOP_N,
) -> list[dict[str, Any]]:
    """资金力度：|合约净流| + |现货净流|，方向由合计净值决定。"""
    eligible = [r for r in rows if r.get("status") != "warming"]
    scored: list[tuple[dict[str, Any], float, str]] = []

    for row in eligible:
        contract = _win(row, "flow_by_tf", tf)["net_usd"]
        spot = _win(row, "spot_flow_by_tf", tf)["net_usd"]
        total = contract + spot
        score = abs(contract) + abs(spot)
        if score <= 0:
            continue
        direction = "inflow" if total >= 0 else "outflow"
        scored.append((row, score, direction))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [
        _slim_bias_item(row, rank=i, score=score, direction=direction)
        for i, (row, score, direction) in enumerate(scored[:top_n], start=1)
    ]
