import type { ChartTimeframe } from "./chartTimeframe";
import type { PatternCandle } from "../types";

const FSTREAM_WS = "wss://fstream.binance.com";

export interface LiveKlineUpdate {
  candle: PatternCandle;
  closed: boolean;
  markPrice?: number;
}

function parseKline(k: Record<string, unknown>): PatternCandle {
  return {
    time: Math.floor(Number(k.t) / 1000),
    open: Number(k.o),
    high: Number(k.h),
    low: Number(k.l),
    close: Number(k.c),
    volume: Number(k.v ?? 0),
  };
}

/** 币安 U 本位：K 线实时推送 + 标记价格（头部报价）。 */
export function binanceChartLiveWsUrl(symbol: string, interval: ChartTimeframe): string {
  const sym = symbol.toLowerCase();
  const streams = `${sym}@kline_${interval}/${sym}@markPrice@1s`;
  return `${FSTREAM_WS}/stream?streams=${streams}`;
}

export function parseBinanceChartLiveMessage(raw: string): LiveKlineUpdate | null {
  try {
    const msg = JSON.parse(raw) as {
      stream?: string;
      data?: Record<string, unknown>;
    };
    const data = msg.data;
    if (!data) return null;

    if (data.e === "kline" && data.k && typeof data.k === "object") {
      const k = data.k as Record<string, unknown>;
      return {
        candle: parseKline(k),
        closed: Boolean(k.x),
      };
    }

    if (data.e === "markPriceUpdate" && data.p != null) {
      return {
        candle: { time: 0, open: 0, high: 0, low: 0, close: 0 },
        closed: false,
        markPrice: Number(data.p),
      };
    }
  } catch {
    /* ignore */
  }
  return null;
}
