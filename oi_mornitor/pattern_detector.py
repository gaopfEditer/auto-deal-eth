"""
形态拐点检测 — 次高点(LH) + 更高低点(HL) + 多头延续(HH)。

阶段 1：SEARCHING_TOP → STAGE_1_LH_DETECTED（BB-Wicks 上轨插针 / MACD 高位走弱）
阶段 2：STAGE_1_LH_DETECTED → TRIGGER_SIGNAL（HL 抬高 + 带量突破夹角高点 + MACD 金叉放大）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from oi_mornitor.breakout_detector import klines_to_df
from oi_mornitor.config import (
    PATTERN_BB_LENGTH,
    PATTERN_BB_MULT,
    PATTERN_PIVOT_WINDOW,
    PATTERN_STAGE2_VOL_MULT,
    PATTERN_WICK_RATIO,
    STRATEGY_VEGAS_FILTER,
    STRATEGY_VEGAS_PERIODS,
)
from oi_mornitor.strategy.indicators import detect_inverted_hammer, detect_shooting_star

STATUS_SEARCHING = "SEARCHING_TOP"
STATUS_LH = "STAGE_1_LH_DETECTED"
STATUS_WAITING = "WAITING_FOR_HL"
STATUS_TRIGGER = "TRIGGER_SIGNAL"
STATUS_EXPIRED = "EXPIRED"

STATUS_LABELS: dict[str, str] = {
    STATUS_SEARCHING: "寻找顶部",
    STATUS_LH: "次高点确认",
    STATUS_WAITING: "等待更高低点",
    STATUS_TRIGGER: "多头爆发",
    STATUS_EXPIRED: "已过期",
}


@dataclass
class PatternSnapshot:
    status: str
    h_max: float = 0.0
    lh_price: float = 0.0
    l1: float = 0.0
    hl: float = 0.0
    trigger_price: float = 0.0
    hh_price: float = 0.0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "h_max": self.h_max,
            "lh_price": self.lh_price,
            "l1": self.l1,
            "hl": self.hl,
            "trigger_price": self.trigger_price,
            "hh_price": self.hh_price,
            "message": self.message,
        }


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["bb_basis"] = out["close"].rolling(PATTERN_BB_LENGTH).mean()
    out["bb_std"] = out["close"].rolling(PATTERN_BB_LENGTH).std(ddof=0)
    out["bb_upper"] = out["bb_basis"] + PATTERN_BB_MULT * out["bb_std"]
    out["bb_lower"] = out["bb_basis"] - PATTERN_BB_MULT * out["bb_std"]

    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    out["vol_sma20"] = out["volume"].rolling(20).mean()

    # Vegas 双通道：过滤线 12 + A组 144/169 + B组 576/676
    out["vegas_filter"] = out["close"].ewm(span=STRATEGY_VEGAS_FILTER, adjust=False).mean()
    for i, period in enumerate(STRATEGY_VEGAS_PERIODS, start=1):
        out[f"vegas_e{i}"] = out["close"].ewm(span=period, adjust=False).mean()

    win = PATTERN_PIVOT_WINDOW
    out["is_pivot_high"] = out["high"] == out["high"].rolling(win, center=True).max()
    out["is_pivot_low"] = out["low"] == out["low"].rolling(win, center=True).min()
    out["is_pivot_high"] = out["is_pivot_high"].fillna(False)
    out["is_pivot_low"] = out["is_pivot_low"].fillna(False)
    return out


def _bb_upper_wick(row: pd.Series) -> bool:
    body = abs(float(row["close"]) - float(row["open"]))
    upper_wick = float(row["high"]) - max(float(row["open"]), float(row["close"]))
    if float(row["high"]) <= float(row["bb_upper"]):
        return False
    if float(row["close"]) >= float(row["bb_upper"]):
        return False
    if upper_wick <= 0:
        return False
    return body == 0 or upper_wick / body >= PATTERN_WICK_RATIO


def _macd_top_weak(df: pd.DataFrame) -> bool:
    if len(df) < 3:
        return False
    last = df.iloc[-1]
    prev = df.iloc[-2]
    death_cross = float(last["macd"]) < float(last["macd_signal"])
    hist_shrink = (
        float(last["macd_hist"]) > 0
        and float(last["macd_hist"]) < float(prev["macd_hist"])
    )
    return death_cross or hist_shrink


def _macd_bull_filter(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False
    last = df.iloc[-1]
    prev = df.iloc[-2]
    golden = float(last["macd"]) > float(last["macd_signal"])
    hist_grow = float(last["macd_hist"]) > float(prev["macd_hist"])
    return golden and hist_grow


def detect_stage1_lh(df: pd.DataFrame) -> PatternSnapshot | None:
    """锁定次高点 + 顶部 BB-Wicks / MACD 共振。"""
    pivot_highs = df[df["is_pivot_high"]].tail(2)
    if len(pivot_highs) < 2:
        return None

    h_max = float(pivot_highs.iloc[0]["high"])
    lh_price = float(pivot_highs.iloc[1]["high"])
    if lh_price >= h_max:
        return None

    last = df.iloc[-1]
    top_signal = _bb_upper_wick(last) or _macd_top_weak(df)
    if not top_signal:
        return None

    signal = "BB-Wicks 上轨插针" if _bb_upper_wick(last) else "MACD 高位走弱"
    return PatternSnapshot(
        status=STATUS_LH,
        h_max=h_max,
        lh_price=lh_price,
        message=f"次高点确立 · {signal}",
    )


def detect_stage2_trigger(
    df: pd.DataFrame,
    *,
    lh_price: float,
) -> PatternSnapshot | None:
    """更高低点抬高 + 带量突破夹角高点 + MACD 金叉放大。"""
    pivot_lows = df[df["is_pivot_low"]].tail(2)
    if len(pivot_lows) < 2:
        return None

    l1 = float(pivot_lows.iloc[0]["low"])
    hl = float(pivot_lows.iloc[1]["low"])
    if hl <= l1:
        return None

    idx1 = pivot_lows.index[0]
    idx2 = pivot_lows.index[1]
    between = df.loc[idx1:idx2]
    if between.empty:
        return None

    trigger_price = float(between["high"].max())
    last = df.iloc[-1]
    close = float(last["close"])
    volume = float(last["volume"])
    vol_sma = float(last["vol_sma20"]) if pd.notna(last["vol_sma20"]) else 0.0

    if close <= trigger_price:
        return PatternSnapshot(
            status=STATUS_WAITING,
            lh_price=lh_price,
            l1=l1,
            hl=hl,
            trigger_price=trigger_price,
            message=f"更高低点 {hl:.4g} > {l1:.4g}，待突破 {trigger_price:.4g}",
        )

    if vol_sma <= 0 or volume <= vol_sma * PATTERN_STAGE2_VOL_MULT:
        return PatternSnapshot(
            status=STATUS_WAITING,
            lh_price=lh_price,
            l1=l1,
            hl=hl,
            trigger_price=trigger_price,
            message="结构成型，量能不足",
        )

    if not _macd_bull_filter(df):
        return PatternSnapshot(
            status=STATUS_WAITING,
            lh_price=lh_price,
            l1=l1,
            hl=hl,
            trigger_price=trigger_price,
            message="结构成型，MACD 未共振",
        )

    return PatternSnapshot(
        status=STATUS_TRIGGER,
        lh_price=lh_price,
        l1=l1,
        hl=hl,
        trigger_price=trigger_price,
        hh_price=close,
        message=f"带量突破 {trigger_price:.4g} · MACD 金叉放大",
    )


def evaluate_pattern(
    klines: list[list],
    *,
    current_status: str,
    state: dict[str, float],
) -> tuple[PatternSnapshot, bool]:
    """
    单币种形态评估。
    返回 (快照, 是否发射扳机告警)。
    """
    df = klines_to_df(klines)
    if len(df) < PATTERN_BB_LENGTH + PATTERN_PIVOT_WINDOW:
        return PatternSnapshot(status=current_status or STATUS_SEARCHING), False

    df = enrich_indicators(df)
    kline_close_time = int(df.iloc[-1]["close_time"])

    if current_status in (STATUS_SEARCHING, STATUS_EXPIRED, ""):
        snap = detect_stage1_lh(df)
        if snap:
            return snap, False
        return PatternSnapshot(status=STATUS_SEARCHING), False

    if current_status in (STATUS_LH, STATUS_WAITING):
        lh_price = state.get("lh_price", 0.0)
        snap = detect_stage2_trigger(df, lh_price=lh_price)
        if snap and snap.status == STATUS_TRIGGER:
            return snap, True
        if snap:
            return snap, False
        return PatternSnapshot(
            status=STATUS_LH,
            h_max=state.get("h_max", 0.0),
            lh_price=lh_price,
            message="等待深V洗盘与二次回探",
        ), False

    return PatternSnapshot(status=current_status), False


def _ts_sec(open_time_ms: int) -> int:
    return int(open_time_ms // 1000)


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _sort_series_by_time(items: list[dict[str, Any]], key: str = "time") -> list[dict[str, Any]]:
    return sorted(items, key=lambda x: x[key])


def _dedupe_candles(candles: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    seen: set[int] = set()
    out: list[dict[str, float | int]] = []
    for c in sorted(candles, key=lambda x: int(x["time"])):
        t = int(c["time"])
        if t in seen:
            continue
        seen.add(t)
        out.append(c)
    return out


def build_pattern_chart_payload(
    klines: list[list],
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    构建 K 线 + 形态拐点标注数据，供前端图表渲染。
    """
    state = state or {}
    df = klines_to_df(klines)
    if df.empty:
        return {
            "candles": [],
            "markers": [],
            "price_lines": [],
            "analysis": {},
            "bb": {"upper": [], "mid": [], "lower": []},
            "vegas": {"filter": [], "a1": [], "a2": [], "b1": [], "b2": []},
            "macd": {"line": [], "signal": [], "hist": []},
        }

    df = enrich_indicators(df)
    candles: list[dict[str, float | int]] = []
    bb_upper: list[dict[str, float | int]] = []
    bb_mid: list[dict[str, float | int]] = []
    bb_lower: list[dict[str, float | int]] = []
    macd_line: list[dict[str, float | int]] = []
    macd_signal: list[dict[str, float | int]] = []
    macd_hist: list[dict[str, float | int]] = []
    vegas: dict[str, list[dict[str, float | int]]] = {
        "filter": [],
        "a1": [],
        "a2": [],
        "b1": [],
        "b2": [],
    }
    vegas_keys = list(vegas.keys())
    vegas_cols = ["vegas_filter"] + [f"vegas_e{i}" for i in range(1, len(STRATEGY_VEGAS_PERIODS) + 1)]

    for row in df.itertuples(index=False):
        t = _ts_sec(int(row.open_time))
        candles.append({
            "time": t,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        })
        if pd.notna(row.bb_upper):
            bb_upper.append({"time": t, "value": float(row.bb_upper)})
            bb_mid.append({"time": t, "value": float(row.bb_basis)})
            bb_lower.append({"time": t, "value": float(row.bb_lower)})
        if pd.notna(getattr(row, "macd", None)):
            macd_line.append({"time": t, "value": float(row.macd)})
            macd_signal.append({"time": t, "value": float(row.macd_signal)})
            macd_hist.append({"time": t, "value": float(row.macd_hist)})
        for key, col in zip(vegas_keys, vegas_cols):
            val = getattr(row, col, None)
            if val is not None and pd.notna(val):
                vegas[key].append({"time": t, "value": float(val)})

    markers: list[dict[str, Any]] = []
    analysis: dict[str, Any] = {
        "status": state.get("status", STATUS_SEARCHING),
        "status_label": STATUS_LABELS.get(state.get("status", ""), "寻找顶部"),
        "message": state.get("message", ""),
    }

    pivot_highs = df[df["is_pivot_high"]].tail(2)
    pivot_lows = df[df["is_pivot_low"]].tail(2)

    h_max = _safe_float(state.get("h_max"))
    lh_price = _safe_float(state.get("lh_price"))
    l1 = _safe_float(state.get("l1"))
    hl = _safe_float(state.get("hl"))
    trigger_price = _safe_float(state.get("trigger_price"))
    hh_price = _safe_float(state.get("hh_price"))

    if len(pivot_highs) >= 2:
        h_row = pivot_highs.iloc[0]
        lh_row = pivot_highs.iloc[1]
        h_max = h_max or float(h_row["high"])
        lh_price = lh_price or float(lh_row["high"])
        markers.append({
            "time": _ts_sec(int(h_row["open_time"])),
            "position": "aboveBar",
            "color": "#ff5252",
            "shape": "arrowDown",
            "text": "① H_max",
            "price": h_max,
            "kind": "h_max",
        })
        if lh_price < h_max:
            markers.append({
                "time": _ts_sec(int(lh_row["open_time"])),
                "position": "aboveBar",
                "color": "#ffc107",
                "shape": "arrowDown",
                "text": "② LH",
                "price": lh_price,
                "kind": "lh",
            })

    if len(pivot_lows) >= 1:
        l1_row = pivot_lows.iloc[0]
        l1 = l1 or float(l1_row["low"])
        markers.append({
            "time": _ts_sec(int(l1_row["open_time"])),
            "position": "belowBar",
            "color": "#ff5252",
            "shape": "arrowUp",
            "text": "L₁ 洗盘",
            "price": l1,
            "kind": "l1",
        })

    if len(pivot_lows) >= 2:
        hl_row = pivot_lows.iloc[1]
        hl = hl or float(hl_row["low"])
        if hl > l1:
            markers.append({
                "time": _ts_sec(int(hl_row["open_time"])),
                "position": "belowBar",
                "color": "#00e676",
                "shape": "arrowUp",
                "text": "③ HL",
                "price": hl,
                "kind": "hl",
            })
            idx1 = pivot_lows.index[0]
            idx2 = pivot_lows.index[1]
            between = df.loc[idx1:idx2]
            if not between.empty:
                trigger_price = trigger_price or float(between["high"].max())
                peak_row = between.loc[between["high"].idxmax()]
                markers.append({
                    "time": _ts_sec(int(peak_row["open_time"])),
                    "position": "aboveBar",
                    "color": "#64b5f6",
                    "shape": "circle",
                    "text": "夹角高点",
                    "price": trigger_price,
                    "kind": "mid_peak",
                })

    last = df.iloc[-1]
    if hh_price > 0 or str(state.get("status", "")) == STATUS_TRIGGER:
        markers.append({
            "time": _ts_sec(int(last["open_time"])),
            "position": "aboveBar",
            "color": "#00e676",
            "shape": "arrowUp",
            "text": "④ HH",
            "price": hh_price or float(last["close"]),
            "kind": "hh",
        })

    if _bb_upper_wick(last):
        markers.append({
            "time": _ts_sec(int(last["open_time"])),
            "position": "aboveBar",
            "color": "#e040fb",
            "shape": "circle",
            "text": "BB-Wicks",
            "price": float(last["high"]),
            "kind": "bb_wick",
        })

    # 全量扫描射击之星 / 倒锤子（对齐 BB-Wicks Pine）
    for _, crow in df.iterrows():
        if pd.isna(crow.get("bb_basis")):
            continue
        below_mid = float(crow["close"]) < float(crow["bb_basis"])
        shoot = detect_shooting_star(crow)
        if shoot:
            markers.append({
                "time": _ts_sec(int(crow["open_time"])),
                "position": "aboveBar",
                "color": "#ff4081",
                "shape": "arrowDown",
                "text": "射击之星",
                "price": float(crow["high"]),
                "kind": "shooting_star",
            })
            continue
        if below_mid and detect_inverted_hammer(crow):
            markers.append({
                "time": _ts_sec(int(crow["open_time"])),
                "position": "belowBar",
                "color": "#00bcd4",
                "shape": "arrowUp",
                "text": "倒锤子",
                "price": float(crow["low"]),
                "kind": "inverted_hammer",
            })

    price_lines: list[dict[str, Any]] = []
    line_defs = [
        ("h_max", h_max, "#ff5252", "H_max 供给墙"),
        ("lh", lh_price, "#ffc107", "LH 次高点"),
        ("l1", l1, "#ff8a80", "L₁ 洗盘低点"),
        ("hl", hl, "#00e676", "HL 更高低点"),
        ("trigger", trigger_price, "#64b5f6", "扳机线"),
    ]
    for kind, price, color, title in line_defs:
        if price > 0:
            price_lines.append({"kind": kind, "price": price, "color": color, "title": title})

    analysis.update({
        "h_max": h_max,
        "lh_price": lh_price,
        "l1": l1,
        "hl": hl,
        "trigger_price": trigger_price,
        "hh_price": hh_price,
        "last_price": float(last["close"]),
        "bb_wick_top": bool(_bb_upper_wick(last)),
        "macd_bull": bool(_macd_bull_filter(df)),
        "macd_top_weak": bool(_macd_top_weak(df)),
    })

    return {
        "candles": _dedupe_candles(candles),
        "markers": _sort_series_by_time(markers),
        "price_lines": price_lines,
        "bb": {
            "upper": _sort_series_by_time(bb_upper),
            "mid": _sort_series_by_time(bb_mid),
            "lower": _sort_series_by_time(bb_lower),
        },
        "vegas": {key: _sort_series_by_time(pts) for key, pts in vegas.items()},
        "macd": {
            "line": _sort_series_by_time(macd_line),
            "signal": _sort_series_by_time(macd_signal),
            "hist": _sort_series_by_time(macd_hist),
        },
        "analysis": analysis,
    }
