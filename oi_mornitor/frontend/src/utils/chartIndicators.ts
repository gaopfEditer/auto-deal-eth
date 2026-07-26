/**
 * 前端本地计算 BB / Vegas / MACD / 简易形态标记（对齐后端 pattern_detector 主要字段）。
 * K 线由浏览器直连交易所，指标不再依赖后端代算。
 */
import type {
  PatternCandle,
  PatternChartAnalysis,
  PatternChartMarker,
  PatternPriceLine,
} from "../types";

const BB_LEN = 20;
const BB_MULT = 2;
const PIVOT_WIN = 11;
const VEGAS_FILTER = 12;
const VEGAS_PERIODS = [144, 169, 576, 676] as const;

type Pt = { time: number; value: number };

function sma(values: number[], period: number, i: number): number | null {
  if (i + 1 < period) return null;
  let s = 0;
  for (let j = i - period + 1; j <= i; j++) s += values[j];
  return s / period;
}

function stdev(values: number[], period: number, i: number, mean: number): number {
  let s = 0;
  for (let j = i - period + 1; j <= i; j++) {
    const d = values[j] - mean;
    s += d * d;
  }
  return Math.sqrt(s / period);
}

/** EMA（与 pandas ewm(span, adjust=False) 一致：α=2/(span+1)） */
function emaSeries(values: number[], span: number): (number | null)[] {
  const alpha = 2 / (span + 1);
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (!values.length) return out;
  let prev = values[0];
  out[0] = prev;
  for (let i = 1; i < values.length; i++) {
    prev = alpha * values[i] + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}

function isPivotExtreme(
  highs: number[],
  lows: number[],
  i: number,
  win: number,
  mode: "high" | "low",
): boolean {
  const half = Math.floor(win / 2);
  if (i < half || i + half >= highs.length) return false;
  const center = mode === "high" ? highs[i] : lows[i];
  for (let j = i - half; j <= i + half; j++) {
    if (j === i) continue;
    if (mode === "high" && highs[j] > center) return false;
    if (mode === "low" && lows[j] < center) return false;
  }
  return true;
}

function detectShootingStar(c: PatternCandle): boolean {
  const body = Math.abs(c.close - c.open);
  const range = c.high - c.low;
  if (range <= 0) return false;
  const upper = c.high - Math.max(c.open, c.close);
  const lower = Math.min(c.open, c.close) - c.low;
  return upper >= body * 2 && upper >= range * 0.5 && lower <= body * 0.5;
}

function detectInvertedHammer(c: PatternCandle): boolean {
  const body = Math.abs(c.close - c.open);
  const range = c.high - c.low;
  if (range <= 0) return false;
  const upper = c.high - Math.max(c.open, c.close);
  const lower = Math.min(c.open, c.close) - c.low;
  return upper >= body * 2 && upper >= range * 0.5 && lower <= body;
}

export function buildChartFromCandles(
  candles: PatternCandle[],
  state?: Record<string, unknown> | null,
): {
  bb: { upper: Pt[]; mid: Pt[]; lower: Pt[] };
  vegas: Record<"filter" | "a1" | "a2" | "b1" | "b2", Pt[]>;
  macd: { line: Pt[]; signal: Pt[]; hist: Pt[] };
  markers: PatternChartMarker[];
  price_lines: PatternPriceLine[];
  analysis: PatternChartAnalysis;
} {
  const closes = candles.map((c) => c.close);
  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);

  const bb = { upper: [] as Pt[], mid: [] as Pt[], lower: [] as Pt[] };
  for (let i = 0; i < candles.length; i++) {
    const mean = sma(closes, BB_LEN, i);
    if (mean == null) continue;
    const sd = stdev(closes, BB_LEN, i, mean);
    const t = candles[i].time;
    bb.mid.push({ time: t, value: mean });
    bb.upper.push({ time: t, value: mean + BB_MULT * sd });
    bb.lower.push({ time: t, value: mean - BB_MULT * sd });
  }

  const filterE = emaSeries(closes, VEGAS_FILTER);
  const vegasEs = VEGAS_PERIODS.map((p) => emaSeries(closes, p));
  const vegas = {
    filter: [] as Pt[],
    a1: [] as Pt[],
    a2: [] as Pt[],
    b1: [] as Pt[],
    b2: [] as Pt[],
  };
  const vegasKeys = ["filter", "a1", "a2", "b1", "b2"] as const;
  for (let i = 0; i < candles.length; i++) {
    const t = candles[i].time;
    const vals = [filterE[i], vegasEs[0][i], vegasEs[1][i], vegasEs[2][i], vegasEs[3][i]];
    vegasKeys.forEach((key, ki) => {
      const v = vals[ki];
      if (v != null && Number.isFinite(v)) vegas[key].push({ time: t, value: v });
    });
  }

  const ema12 = emaSeries(closes, 12);
  const ema26 = emaSeries(closes, 26);
  const macdRaw: number[] = closes.map((_, i) => {
    const a = ema12[i];
    const b = ema26[i];
    return a != null && b != null ? a - b : 0;
  });
  const macdSignal = emaSeries(macdRaw, 9);
  const macd = { line: [] as Pt[], signal: [] as Pt[], hist: [] as Pt[] };
  for (let i = 0; i < candles.length; i++) {
    if (ema12[i] == null || ema26[i] == null) continue;
    const t = candles[i].time;
    const m = macdRaw[i];
    const s = macdSignal[i] ?? m;
    macd.line.push({ time: t, value: m });
    macd.signal.push({ time: t, value: s });
    macd.hist.push({ time: t, value: m - s });
  }

  const markers: PatternChartMarker[] = [];
  const pivotHighIdx: number[] = [];
  const pivotLowIdx: number[] = [];
  for (let i = 0; i < candles.length; i++) {
    if (isPivotExtreme(highs, lows, i, PIVOT_WIN, "high")) pivotHighIdx.push(i);
    if (isPivotExtreme(highs, lows, i, PIVOT_WIN, "low")) pivotLowIdx.push(i);
  }
  const ph = pivotHighIdx.slice(-2);
  const pl = pivotLowIdx.slice(-2);

  const st = state || {};
  let hMax = Number(st.h_max || 0);
  let lh = Number(st.lh_price || 0);
  let l1 = Number(st.l1 || 0);
  let hl = Number(st.hl || 0);
  let trigger = Number(st.trigger_price || 0);
  const hh = Number(st.hh_price || 0);

  if (ph.length >= 2) {
    const hRow = candles[ph[0]];
    const lhRow = candles[ph[1]];
    hMax = hMax || hRow.high;
    lh = lh || lhRow.high;
    markers.push({
      time: hRow.time,
      position: "aboveBar",
      color: "#ff5252",
      shape: "arrowDown",
      text: "① H_max",
      price: hMax,
      kind: "h_max",
    });
    if (lh < hMax) {
      markers.push({
        time: lhRow.time,
        position: "aboveBar",
        color: "#ffc107",
        shape: "arrowDown",
        text: "② LH",
        price: lh,
        kind: "lh",
      });
    }
  }
  if (pl.length >= 1) {
    const lRow = candles[pl[0]];
    l1 = l1 || lRow.low;
    markers.push({
      time: lRow.time,
      position: "belowBar",
      color: "#ff5252",
      shape: "arrowUp",
      text: "L₁ 洗盘",
      price: l1,
      kind: "l1",
    });
  }
  if (pl.length >= 2) {
    const hlRow = candles[pl[1]];
    hl = hl || hlRow.low;
    if (hl > l1) {
      markers.push({
        time: hlRow.time,
        position: "belowBar",
        color: "#00e676",
        shape: "arrowUp",
        text: "③ HL",
        price: hl,
        kind: "hl",
      });
    }
  }

  const bbByTime = new Map(bb.mid.map((p) => [p.time, p.value]));
  for (const c of candles) {
    const mid = bbByTime.get(c.time);
    if (mid == null) continue;
    if (detectShootingStar(c) && c.close < mid) {
      markers.push({
        time: c.time,
        position: "aboveBar",
        color: "#ff4081",
        shape: "arrowDown",
        text: "射击之星",
        price: c.high,
        kind: "shooting_star",
      });
    }
    if (detectInvertedHammer(c) && c.close > mid) {
      markers.push({
        time: c.time,
        position: "belowBar",
        color: "#00bcd4",
        shape: "arrowUp",
        text: "倒锤子",
        price: c.low,
        kind: "inverted_hammer",
      });
    }
  }

  const price_lines: PatternPriceLine[] = [];
  const lineSpecs: { kind: string; price: number; color: string; title: string }[] = [
    { kind: "h_max", price: hMax, color: "#ff5252", title: "H_max" },
    { kind: "lh", price: lh, color: "#ffc107", title: "LH" },
    { kind: "l1", price: l1, color: "#ff8a80", title: "L₁" },
    { kind: "hl", price: hl, color: "#00e676", title: "HL" },
    { kind: "trigger", price: trigger, color: "#64b5f6", title: "扳机" },
    { kind: "hh", price: hh, color: "#00e676", title: "HH" },
  ];
  for (const s of lineSpecs) {
    if (s.price > 0) price_lines.push(s);
  }

  const analysis: PatternChartAnalysis = {
    status: String(st.status || ""),
    status_label: String(st.status_label || ""),
    message: String(st.message || ""),
    h_max: hMax || undefined,
    lh_price: lh || undefined,
    l1: l1 || undefined,
    hl: hl || undefined,
    trigger_price: trigger || undefined,
    hh_price: hh || undefined,
    last_price: candles.length ? candles[candles.length - 1].close : undefined,
  };

  return { bb, vegas, macd, markers, price_lines, analysis };
}
