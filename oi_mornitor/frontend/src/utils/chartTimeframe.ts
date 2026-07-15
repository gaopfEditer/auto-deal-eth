import type { PatternCandle, PatternChartData } from "../types";

export const CHART_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"] as const;
export type ChartTimeframe = (typeof CHART_TIMEFRAMES)[number];

export const CHART_DEFAULT_LIMIT = 500;
export const CHART_LOAD_CHUNK = 300;
export const CHART_REFRESH_TAIL = 80;
export const CHART_VISIBLE_BARS = 160;

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

export async function fetchPatternChart(
  symbol: string,
  interval: ChartTimeframe,
  opts?: { limit?: number; endTimeMs?: number },
): Promise<PatternChartData> {
  const res = await fetch(chartApiUrl(symbol, interval, opts));
  return res.json() as Promise<PatternChartData>;
}

/** 最早一根 K 线的 open_time（毫秒），用于向左分页。 */
export function oldestCandleOpenMs(candles: PatternCandle[]): number | null {
  if (!candles.length) return null;
  return candles[0].time * 1000;
}
