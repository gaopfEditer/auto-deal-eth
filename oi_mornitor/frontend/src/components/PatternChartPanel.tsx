import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  ColorType,
  createChart,
  type CandlestickData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LineData,
  type LogicalRange,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PatternCandle, PatternChartData, PatternState } from "../types";
import { fmtNum, fmtPct } from "../utils/format";
import { coinInitial, displaySymbol } from "../utils/symbol";
import type { TickerRow } from "../types";
import { useBinanceChartLive } from "../hooks/useBinanceChartLive";
import type { LiveKlineUpdate } from "../utils/binanceWs";
import {
  CHART_DEFAULT_LIMIT,
  CHART_LOAD_CHUNK,
  CHART_REFRESH_TAIL,
  CHART_TIMEFRAMES,
  CHART_VISIBLE_BARS,
  chartMetaRefreshMs,
  type ChartTimeframe,
  fetchPatternChart,
  mergeBbSeries,
  mergeCandlesByTime,
  oldestCandleOpenMs,
} from "../utils/chartTimeframe";
import { chartLocalization, chartTimeScaleOptions, formatCandleLocalTime } from "../utils/chartLocale";

interface Props {
  symbol: string;
  state?: PatternState;
  liveTicker?: TickerRow;
  onClose: () => void;
}

const MARKER_LEGEND = [
  { kind: "h_max", label: "① H_max 绝对高点", color: "#ff5252" },
  { kind: "lh", label: "② LH 次高点", color: "#ffc107" },
  { kind: "l1", label: "L₁ 洗盘低点", color: "#ff8a80" },
  { kind: "hl", label: "③ HL 更高低点", color: "#00e676" },
  { kind: "mid_peak", label: "夹角反弹高点", color: "#64b5f6" },
  { kind: "trigger", label: "扳机线", color: "#64b5f6" },
  { kind: "hh", label: "④ HH 更高高点", color: "#00e676" },
  { kind: "bb_wick", label: "BB-Wicks 插针", color: "#e040fb" },
];

function toCandleData(candles: PatternCandle[]): CandlestickData[] {
  return candles.map((c) => ({
    time: c.time as UTCTimestamp,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
}

export const PatternChartPanel = memo(function PatternChartPanel({
  symbol,
  state,
  liveTicker,
  onClose,
}: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const upperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);

  const candlesRef = useRef<PatternCandle[]>([]);
  const hasMoreRef = useRef(true);
  const loadingMoreRef = useRef(false);
  const timeframeRef = useRef<ChartTimeframe>("15m");
  const metaRef = useRef<PatternChartData | null>(null);

  const [timeframe, setTimeframe] = useState<ChartTimeframe>("15m");
  const [data, setData] = useState<PatternChartData | null>(null);
  const [candleCount, setCandleCount] = useState(0);
  const [lastCandleTime, setLastCandleTime] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [err, setErr] = useState("");

  const clearPriceLines = useCallback(() => {
    const series = seriesRef.current;
    if (!series) return;
    for (const line of priceLinesRef.current) {
      series.removePriceLine(line);
    }
    priceLinesRef.current = [];
  }, []);

  const applyPriceLines = useCallback((payload: PatternChartData) => {
    const series = seriesRef.current;
    if (!series || payload.partial) return;
    clearPriceLines();
    for (const line of payload.price_lines ?? []) {
      priceLinesRef.current.push(
        series.createPriceLine({
          price: line.price,
          color: line.color,
          lineWidth: 1,
          lineStyle: line.kind === "trigger" ? 2 : 0,
          axisLabelVisible: true,
          title: line.title,
        }),
      );
    }
  }, [clearPriceLines]);

  const applyChartSeries = useCallback(
    (payload: PatternChartData, candles: PatternCandle[], opts?: { isPrepend?: boolean }) => {
      const series = seriesRef.current;
      const chart = chartApi.current;
      if (!series || !chart) return;

      try {
        const prevRange = chart.timeScale().getVisibleLogicalRange();
        const prevLen = candlesRef.current.length;
        const sortedCandles = [...candles]
          .sort((a, b) => a.time - b.time)
          .filter((c, i, arr) => i === 0 || c.time !== arr[i - 1].time);
        const prepended = opts?.isPrepend ? sortedCandles.length - prevLen : 0;

        series.setData(toCandleData(sortedCandles));

        const rawMarkers = payload.partial ? metaRef.current?.markers : payload.markers;
        const markers = [...(rawMarkers ?? [])].sort((a, b) => a.time - b.time);
        if (markers.length) {
          series.setMarkers(
            markers.map(
              (m) =>
                ({
                  time: m.time as UTCTimestamp,
                  position: m.position,
                  color: m.color,
                  shape: m.shape,
                  text: m.text,
                }) as SeriesMarker<UTCTimestamp>,
            ),
          );
        } else if (!payload.partial) {
          series.setMarkers([]);
        }

        if (!payload.partial) {
          applyPriceLines(payload);
          metaRef.current = payload;
        }

        if (upperRef.current) {
          const upperPts = [...(payload.bb?.upper ?? [])].sort((a, b) => a.time - b.time);
          upperRef.current.setData(
            upperPts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) as LineData[],
          );
        }
        if (lowerRef.current) {
          const lowerPts = [...(payload.bb?.lower ?? [])].sort((a, b) => a.time - b.time);
          lowerRef.current.setData(
            lowerPts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) as LineData[],
          );
        }

        candlesRef.current = sortedCandles;
        setCandleCount(sortedCandles.length);
        setLastCandleTime(sortedCandles.at(-1)?.time ?? null);

        if (prevRange && prepended > 0) {
          chart.timeScale().setVisibleLogicalRange({
            from: prevRange.from + prepended,
            to: prevRange.to + prepended,
          });
        } else if (!prevRange || prevLen === 0) {
          const to = sortedCandles.length;
          const from = Math.max(0, to - CHART_VISIBLE_BARS);
          chart.timeScale().setVisibleLogicalRange({ from, to: to + 2 });
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : "图表渲染失败");
      }
    },
    [applyPriceLines],
  );

  const loadMoreHistory = useCallback(async () => {
    if (loadingMoreRef.current || !hasMoreRef.current) return;
    const oldestMs = oldestCandleOpenMs(candlesRef.current);
    if (oldestMs == null) return;

    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const chunk = await fetchPatternChart(symbol, timeframeRef.current, {
        limit: CHART_LOAD_CHUNK,
        endTimeMs: oldestMs - 1,
      });
      if (!chunk.ok || !chunk.candles?.length) {
        hasMoreRef.current = false;
        setHasMore(false);
        return;
      }
      hasMoreRef.current = chunk.has_more !== false;
      setHasMore(hasMoreRef.current);

      const merged = mergeCandlesByTime(candlesRef.current, chunk.candles);
      const mergedUpper = mergeBbSeries(metaRef.current?.bb?.upper ?? [], chunk.bb?.upper ?? []);
      const mergedLower = mergeBbSeries(metaRef.current?.bb?.lower ?? [], chunk.bb?.lower ?? []);
      if (metaRef.current) {
        metaRef.current = {
          ...metaRef.current,
          bb: { upper: mergedUpper, lower: mergedLower },
        };
      }
      applyChartSeries(
        { ...chunk, partial: true, bb: { upper: mergedUpper, lower: mergedLower } },
        merged,
        { isPrepend: true },
      );
    } catch {
      /* 静默 */
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [symbol, applyChartSeries]);

  const refreshLatestRef = useRef<() => void>(() => {});

  const refreshLatest = useCallback(async () => {
    if (loadingMoreRef.current || loading) return;
    try {
      const json = await fetchPatternChart(symbol, timeframeRef.current, {
        limit: CHART_REFRESH_TAIL,
      });
      if (!json.ok || !json.candles?.length) return;

      const merged = mergeCandlesByTime(candlesRef.current, json.candles);
      const mergedUpper = mergeBbSeries(metaRef.current?.bb?.upper ?? [], json.bb?.upper ?? []);
      const mergedLower = mergeBbSeries(metaRef.current?.bb?.lower ?? [], json.bb?.lower ?? []);

      setData({
        ...json,
        candles: merged,
        bb: { upper: mergedUpper, lower: mergedLower },
      });
    } catch {
      /* 静默 */
    }
  }, [symbol, loading]);

  refreshLatestRef.current = () => {
    void refreshLatest();
  };

  const applyLiveCandle = useCallback((candle: PatternCandle, closed: boolean) => {
    const series = seriesRef.current;
    if (!series || candle.time <= 0) return;

    try {
      series.update({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      });

      const candles = candlesRef.current;
      const last = candles[candles.length - 1];
      if (last?.time === candle.time) {
        candles[candles.length - 1] = candle;
      } else if (!last || candle.time > last.time) {
        candlesRef.current = [...candles, candle];
        setCandleCount(candlesRef.current.length);
      }
      setLastCandleTime(candle.time);

      if (closed) refreshLatestRef.current();

      const chart = chartApi.current;
      const range = chart?.timeScale().getVisibleLogicalRange();
      const len = candlesRef.current.length;
      if (chart && range && len > 0 && range.to >= len - 8) {
        const to = len + 2;
        const from = Math.max(0, to - CHART_VISIBLE_BARS);
        chart.timeScale().setVisibleLogicalRange({ from, to });
      }
    } catch {
      /* 静默 */
    }
  }, []);

  const wsEnabled = !loading && !err && Boolean(data?.candles?.length);
  const { markPrice, connected: wsConnected } = useBinanceChartLive(
    symbol,
    timeframe,
    wsEnabled,
    useCallback(
      (update: LiveKlineUpdate) => applyLiveCandle(update.candle, update.closed),
      [applyLiveCandle],
    ),
  );

  useEffect(() => {
    let cancelled = false;
    timeframeRef.current = timeframe;
    candlesRef.current = [];
    hasMoreRef.current = true;
    loadingMoreRef.current = false;
    metaRef.current = null;
    setHasMore(true);
    setLoading(true);
    setErr("");
    setLoadingMore(false);
    setLastCandleTime(null);

    fetchPatternChart(symbol, timeframe, { limit: CHART_DEFAULT_LIMIT })
      .then((json) => {
        if (cancelled) return;
        if (!json.ok) {
          setErr(json.error || "加载失败");
          setData(null);
          return;
        }
        hasMoreRef.current = json.has_more !== false;
        setHasMore(hasMoreRef.current);
        setData(json);
      })
      .catch(() => {
        if (!cancelled) setErr("网络错误");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, timeframe]);

  useEffect(() => {
    if (loading || err || !data?.candles?.length) return;

    const tick = () => {
      if (!document.hidden) void refreshLatest();
    };
    const id = window.setInterval(tick, chartMetaRefreshMs(timeframe));
    return () => window.clearInterval(id);
  }, [symbol, timeframe, loading, err, data?.candles?.length, refreshLatest]);

  useEffect(() => {
    if (!chartRef.current) return;

    if (chartApi.current) {
      chartApi.current.remove();
      chartApi.current = null;
      seriesRef.current = null;
      upperRef.current = null;
      lowerRef.current = null;
      priceLinesRef.current = [];
    }

    const el = chartRef.current;

    try {
      const chart = createChart(el, {
        width: el.clientWidth,
        height: el.clientHeight,
        layout: {
          background: { type: ColorType.Solid, color: "#0a0a0a" },
          textColor: "#9e9e9e",
        },
        grid: {
          vertLines: { color: "#1e1e1e" },
          horzLines: { color: "#1e1e1e" },
        },
        rightPriceScale: { borderColor: "#2a2a2a" },
        localization: chartLocalization,
        timeScale: {
          borderColor: "#2a2a2a",
          ...chartTimeScaleOptions,
        },
        crosshair: { mode: 1 },
        handleScale: {
          axisPressedMouseMove: { time: true, price: true },
          mouseWheel: true,
          pinch: true,
        },
      });

      const series = chart.addCandlestickSeries({
        upColor: "#00e676",
        downColor: "#ff5252",
        borderVisible: false,
        wickUpColor: "#00e676",
        wickDownColor: "#ff5252",
      });

      upperRef.current = chart.addLineSeries({
        color: "rgba(100, 181, 246, 0.45)",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      lowerRef.current = chart.addLineSeries({
        color: "rgba(100, 181, 246, 0.25)",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });

      chartApi.current = chart;
      seriesRef.current = series;

      const onRange = (range: LogicalRange | null) => {
        if (!range || loadingMoreRef.current || !hasMoreRef.current) return;
        if (range.from < 40) void loadMoreHistory();
      };
      chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);

      const onResize = () => {
        if (chartRef.current && chartApi.current) {
          chartApi.current.applyOptions({
            width: chartRef.current.clientWidth,
            height: chartRef.current.clientHeight,
          });
        }
      };
      window.addEventListener("resize", onResize);

      return () => {
        window.removeEventListener("resize", onResize);
        chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
        chart.remove();
        chartApi.current = null;
        seriesRef.current = null;
        upperRef.current = null;
        lowerRef.current = null;
        priceLinesRef.current = [];
      };
    } catch (e) {
      setErr(e instanceof Error ? e.message : "图表初始化失败");
    }
  }, [symbol, timeframe, loadMoreHistory]);

  useEffect(() => {
    if (!data?.candles?.length || !seriesRef.current) return;
    applyChartSeries(data, data.candles);
  }, [data, applyChartSeries]);

  const analysis = data?.analysis;
  const ticker = data?.ticker;
  const lastPrice =
    markPrice ?? liveTicker?.last_price ?? ticker?.last_price ?? analysis?.last_price;
  const pct = liveTicker?.price_change_pct_24h ?? ticker?.price_change_pct_24h;
  const oiUsd = liveTicker?.current_oi_usd ?? ticker?.current_oi_usd;
  const quoteVol = liveTicker?.quote_volume ?? ticker?.quote_volume;
  const statusLabel = analysis?.status_label || state?.status_label || "—";

  const activeKinds = new Set(data?.markers?.map((m) => m.kind).filter(Boolean) ?? []);
  data?.price_lines?.forEach((l) => activeKinds.add(l.kind));

  return (
    <div className="pattern-chart-panel">
      <header className="pattern-chart-head">
        <div className="pattern-chart-title">
          <span className="coin-avatar">{coinInitial(symbol)}</span>
          <div>
            <h2>${displaySymbol(symbol)}</h2>
            <div className="pattern-chart-meta">
              <span className={pct != null && pct >= 0 ? "pos" : "neg"}>
                ${lastPrice != null ? lastPrice.toPrecision(5) : "—"}
                {pct != null ? ` · ${fmtPct(pct)}` : ""}
              </span>
              <span>OI {fmtNum(oiUsd)}</span>
              <span>24h额 {fmtNum(quoteVol)}</span>
              <span className="pat-status-tag">{statusLabel}</span>
            </div>
          </div>
        </div>
        <div className="pattern-chart-head-actions">
          <div className="mercu-timeframes pattern-chart-tf">
            {CHART_TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                type="button"
                className={`tf-btn ${tf === timeframe ? "active" : ""}`}
                onClick={() => setTimeframe(tf)}
                disabled={loading && tf !== timeframe}
              >
                {tf}
              </button>
            ))}
          </div>
          <button type="button" className="pattern-chart-close" onClick={onClose}>
            返回列表
          </button>
        </div>
      </header>

      <div className="pattern-chart-body">
        <aside className="pattern-analysis-side">
          <h3>位置分析</h3>
          {loading && <p className="pattern-empty">加载 K 线…</p>}
          {err && <p className="pattern-err">{err}</p>}
          {!loading && !err && (
            <>
              <p className="pattern-analysis-msg">{analysis?.message || "扫描形态结构中…"}</p>
              <ul className="pattern-marker-legend">
                {MARKER_LEGEND.filter((m) => activeKinds.has(m.kind)).map((m) => (
                  <li key={m.kind}>
                    <span className="legend-dot" style={{ background: m.color }} />
                    {m.label}
                    {analysis && m.kind === "h_max" && analysis.h_max ? (
                      <em>{analysis.h_max.toPrecision(4)}</em>
                    ) : null}
                    {analysis && m.kind === "lh" && analysis.lh_price ? (
                      <em>{analysis.lh_price.toPrecision(4)}</em>
                    ) : null}
                    {analysis && m.kind === "l1" && analysis.l1 ? (
                      <em>{analysis.l1.toPrecision(4)}</em>
                    ) : null}
                    {analysis && m.kind === "hl" && analysis.hl ? (
                      <em>{analysis.hl.toPrecision(4)}</em>
                    ) : null}
                    {analysis && m.kind === "trigger" && analysis.trigger_price ? (
                      <em>{analysis.trigger_price.toPrecision(4)}</em>
                    ) : null}
                  </li>
                ))}
              </ul>
              <div className="pattern-signal-tags">
                {analysis?.bb_wick_top && <span className="sig bb">BB-Wicks 顶部</span>}
                {analysis?.macd_top_weak && <span className="sig macd-weak">MACD 走弱</span>}
                {analysis?.macd_bull && <span className="sig macd-bull">MACD 金叉放大</span>}
              </div>
              <p className="pattern-interval-tag">
                {timeframe} · 已加载 {candleCount} 根
                {lastCandleTime ? ` · 最新 ${formatCandleLocalTime(lastCandleTime)}` : ""}
                {wsConnected ? " · 实时" : " · 连接中…"}
                {loadingMore ? " · 加载更早…" : hasMore ? " · 左滑/缩小可加载更多" : " · 已到最早"}
              </p>
            </>
          )}
        </aside>
        <div className="pattern-chart-wrap" ref={chartRef} />
      </div>
    </div>
  );
});
