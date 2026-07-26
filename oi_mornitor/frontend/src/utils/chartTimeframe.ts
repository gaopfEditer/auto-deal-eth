import type { PatternCandle, PatternChartData, PatternState } from "../types";
import { fetchBinanceFuturesKlines } from "./binanceKlines";
import { buildChartFromCandles } from "./chartIndicators";

export const CHART_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"] as const;
export type ChartTimeframe = (typeof CHART_TIMEFRAMES)[number];

export const CHART_DEFAULT_LIMIT = 500;
export const CHART_LOAD_CHUNK = 300;
export const CHART_REFRESH_TAIL = 80;
export const CHART_VISIBLE_BARS = 160;

/** 默认 client：浏览器直连币安；设 VITE_CHART_KLINES_SOURCE=backend 可回退服务端代拉 */
export function chartKlinesSource(): "client" | "backend" {
  const v = (import.meta.env.VITE_CHART_KLINES_SOURCE as string | undefined)?.trim().toLowerCase();
  return v === "backend" ? "backend" : "client";
}

/** 形态标注 / BB 等元数据 REST 补刷间隔（与 K 线周期对齐）。 */
export function chartMetaRefreshMs(tf: ChartTimeframe): number {
  switch (tf) {
    case "5m":
      return 5 * 60_000;
    case "15m":
      return 15 * 60_000;
    case "30m":
      return 30 * 60_000;
    case "1h":
      return 60 * 60_000;
    case "4h":
      return 4 * 60 * 60_000;
    case "1d":
      return 24 * 60 * 60_000;
    default:
      return 15 * 60_000;
  }
}

export function mergeCandlesByTime(
  existing: PatternCandle[],
  incoming: PatternCandle[],
): PatternCandle[] {
  const map = new Map<number, PatternCandle>();
  for (const c of incoming) map.set(c.time, c);
  for (const c of existing) map.set(c.time, c);
  return [...map.values()].sort((a, b) => a.time - b.time);
}

export function mergeBbSeries(
  existing: { time: number; value: number }[],
  incoming: { time: number; value: number }[],
): { time: number; value: number }[] {
  const map = new Map<number, { time: number; value: number }>();
  for (const p of incoming) map.set(p.time, p);
  for (const p of existing) map.set(p.time, p);
  return [...map.values()].sort((a, b) => a.time - b.time);
}

export type VegasKey = "filter" | "a1" | "a2" | "b1" | "b2";

export function mergeVegasMap(
  existing: Partial<Record<VegasKey, { time: number; value: number }[]>> | undefined,
  incoming: Partial<Record<VegasKey, { time: number; value: number }[]>> | undefined,
): Record<VegasKey, { time: number; value: number }[]> {
  const keys: VegasKey[] = ["filter", "a1", "a2", "b1", "b2"];
  const out = {} as Record<VegasKey, { time: number; value: number }[]>;
  for (const k of keys) {
    out[k] = mergeBbSeries(existing?.[k] ?? [], incoming?.[k] ?? []);
  }
  return out;
}

export type MacdKey = "line" | "signal" | "hist";

export function mergeMacdMap(
  existing: Partial<Record<MacdKey, { time: number; value: number }[]>> | undefined,
  incoming: Partial<Record<MacdKey, { time: number; value: number }[]>> | undefined,
): Record<MacdKey, { time: number; value: number }[]> {
  const keys: MacdKey[] = ["line", "signal", "hist"];
  const out = {} as Record<MacdKey, { time: number; value: number }[]>;
  for (const k of keys) {
    out[k] = mergeBbSeries(existing?.[k] ?? [], incoming?.[k] ?? []);
  }
  return out;
}

export function chartApiUrl(
  symbol: string,
  interval: ChartTimeframe,
  opts?: { limit?: number; endTimeMs?: number },
): string {
  const params = new URLSearchParams({
    symbol,
    interval,
    limit: String(opts?.limit ?? CHART_DEFAULT_LIMIT),
  });
  if (opts?.endTimeMs != null && opts.endTimeMs > 0) {
    params.set("endTime", String(opts.endTimeMs));
  }
  return `/api/patterns/chart?${params.toString()}`;
}

export function chartMetaApiUrl(symbol: string, interval: ChartTimeframe): string {
  const params = new URLSearchParams({ symbol, interval });
  return `/api/patterns/chart-meta?${params.toString()}`;
}

type ChartMetaPayload = {
  ok?: boolean;
  error?: string;
  state?: PatternState;
  ticker?: PatternChartData["ticker"];
  sandbox_markers?: PatternChartData["markers"];
  price_lines?: PatternChartData["price_lines"];
};

async function fetchChartMeta(
  symbol: string,
  interval: ChartTimeframe,
): Promise<ChartMetaPayload> {
  try {
    const res = await fetch(chartMetaApiUrl(symbol, interval));
    return (await res.json()) as ChartMetaPayload;
  } catch {
    return { ok: false, error: "meta 网络错误" };
  }
}

async function fetchPatternChartFromBackend(
  symbol: string,
  interval: ChartTimeframe,
  opts?: { limit?: number; endTimeMs?: number },
): Promise<PatternChartData> {
  const res = await fetch(chartApiUrl(symbol, interval, opts));
  return res.json() as Promise<PatternChartData>;
}

async function fetchPatternChartFromClient(
  symbol: string,
  interval: ChartTimeframe,
  opts?: { limit?: number; endTimeMs?: number },
): Promise<PatternChartData> {
  const partial = opts?.endTimeMs != null && opts.endTimeMs > 0;
  const { candles, rawCount } = await fetchBinanceFuturesKlines(symbol, interval, {
    limit: opts?.limit,
    endTimeMs: opts?.endTimeMs,
  });
  if (!candles.length) {
    return {
      ok: false,
      symbol,
      interval,
      candles: [],
      markers: [],
      price_lines: [],
      bb: { upper: [], lower: [] },
      analysis: {},
      state: {} as PatternState,
      error: "K线数据为空",
    };
  }

  let meta: ChartMetaPayload = {};
  if (!partial) {
    meta = await fetchChartMeta(symbol, interval);
  }

  const built = buildChartFromCandles(
    candles,
    meta.state as unknown as Record<string, unknown> | undefined,
  );
  const sandboxMarkers = meta.sandbox_markers || [];
  const markers = [...built.markers, ...sandboxMarkers];
  const price_lines =
    meta.price_lines && meta.price_lines.length ? meta.price_lines : built.price_lines;

  const last = candles[candles.length - 1];
  const ticker = meta.ticker || { last_price: last.close };

  return {
    ok: true,
    symbol: symbol.toUpperCase(),
    interval,
    partial,
    has_more: rawCount >= (opts?.limit ?? CHART_DEFAULT_LIMIT),
    candles,
    markers,
    price_lines,
    bb: built.bb,
    vegas: built.vegas,
    macd: built.macd,
    analysis: {
      ...built.analysis,
      ...(meta.state
        ? {
            status: meta.state.status,
            status_label: meta.state.status_label,
            message: meta.state.message,
          }
        : {}),
    },
    state: (meta.state || {}) as PatternState,
    ticker,
  };
}

/**
 * 拉取形态图表数据。
 * 默认：浏览器 → 币安 K 线 + 本地指标；状态/沙盒标记仍走本机轻量 API。
 * `VITE_CHART_KLINES_SOURCE=backend` 时整包走服务端（兼容内网无法直连币安）。
 */
export async function fetchPatternChart(
  symbol: string,
  interval: ChartTimeframe,
  opts?: { limit?: number; endTimeMs?: number },
): Promise<PatternChartData> {
  if (chartKlinesSource() === "backend") {
    return fetchPatternChartFromBackend(symbol, interval, opts);
  }
  try {
    return await fetchPatternChartFromClient(symbol, interval, opts);
  } catch (err) {
    console.warn("[chart] 直连币安失败，回退服务端代拉", err);
    return fetchPatternChartFromBackend(symbol, interval, opts);
  }
}

/** 最早一根 K 线的 open_time（毫秒），用于向左分页。 */
export function oldestCandleOpenMs(candles: PatternCandle[]): number | null {
  if (!candles.length) return null;
  return candles[0].time * 1000;
}
