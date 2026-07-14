import { useEffect, useRef, useState } from "react";
import type { ChartTimeframe } from "../utils/chartTimeframe";
import {
  binanceChartLiveWsUrl,
  parseBinanceChartLiveMessage,
  type LiveKlineUpdate,
} from "../utils/binanceWs";

const RETRY_MS = 3000;

export function useBinanceChartLive(
  symbol: string,
  interval: ChartTimeframe,
  enabled: boolean,
  onKline?: (update: LiveKlineUpdate) => void,
) {
  const [markPrice, setMarkPrice] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);
  const onKlineRef = useRef(onKline);
  onKlineRef.current = onKline;

  useEffect(() => {
    if (!enabled || !symbol) {
      setConnected(false);
      setMarkPrice(null);
      return;
    }

    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      ws?.close();
      ws = new WebSocket(binanceChartLiveWsUrl(symbol, interval));

      ws.onopen = () => {
        if (!cancelled) setConnected(true);
      };

      ws.onmessage = (ev) => {
        const parsed = parseBinanceChartLiveMessage(ev.data);
        if (!parsed) return;
        if (parsed.markPrice != null && parsed.markPrice > 0) {
          setMarkPrice(parsed.markPrice);
          return;
        }
        if (parsed.candle.time > 0) {
          onKlineRef.current?.(parsed);
        }
      };

      ws.onerror = () => setConnected(false);

      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) {
          retryTimer = setTimeout(connect, RETRY_MS);
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      ws?.close();
      setConnected(false);
    };
  }, [symbol, interval, enabled]);

  return { markPrice, connected };
}
