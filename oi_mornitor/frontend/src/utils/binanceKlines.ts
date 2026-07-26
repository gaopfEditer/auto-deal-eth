/** 浏览器直连币安 U 本位 REST（分散服务端压力）。可用 VITE_BINANCE_FAPI_BASE 覆盖。 */
import type { ChartTimeframe } from "./chartTimeframe";
import type { PatternCandle } from "../types";

const DEFAULT_FAPI =
  (import.meta.env.VITE_BINANCE_FAPI_BASE as string | undefined)?.replace(/\/$/, "") ||
  "https://fapi.binance.com";

export function binanceFapiBase(): string {
  return DEFAULT_FAPI;
}

/** Binance kline row → 图表 candle（time 为秒）。 */
export function binanceKlineRowToCandle(row: unknown[]): PatternCandle {
  return {
    time: Math.floor(Number(row[0]) / 1000),
    open: Number(row[1]),
    high: Number(row[2]),
    low: Number(row[3]),
    close: Number(row[4]),
    volume: Number(row[5] ?? 0),
  };
}

export async function fetchBinanceFuturesKlines(
  symbol: string,
  interval: ChartTimeframe,
  opts?: { limit?: number; endTimeMs?: number },
): Promise<{ candles: PatternCandle[]; rawCount: number }> {
  const sym = symbol.trim().toUpperCase();
  const limit = Math.min(Math.max(opts?.limit ?? 500, 1), 1500);
  const params = new URLSearchParams({
    symbol: sym,
    interval,
    limit: String(limit),
  });
  if (opts?.endTimeMs != null && opts.endTimeMs > 0) {
    params.set("endTime", String(opts.endTimeMs));
  }
  const url = `${binanceFapiBase()}/fapi/v1/klines?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`币安 K 线 ${res.status}: ${text.slice(0, 120)}`);
  }
  const data = (await res.json()) as unknown[];
  if (!Array.isArray(data)) {
    throw new Error("币安 K 线响应格式错误");
  }
  const candles = data
    .filter((row) => Array.isArray(row) && row.length >= 6)
    .map((row) => binanceKlineRowToCandle(row as unknown[]));
  return { candles, rawCount: data.length };
}
