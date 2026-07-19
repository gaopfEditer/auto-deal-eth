import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LineData,
  type LogicalRange,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PatternCandle, PatternChartData, PatternState } from "../types";
import { chartPriceFormat, formatChartAxisPrice, fmtMetaPrice, fmtNum, fmtPct } from "../utils/format";
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
  mergeMacdMap,
  mergeVegasMap,
  oldestCandleOpenMs,
  type VegasKey,
} from "../utils/chartTimeframe";
import { chartLocalization, chartTimeScaleOptions, formatCandleLocalTime } from "../utils/chartLocale";

interface Props {
  symbol: string;
  state?: PatternState;
  liveTicker?: TickerRow;
  onClose: () => void;
  /** 右键标题：打开与左侧列表相同的操作菜单 */
  onTitleContextMenu?: (e: React.MouseEvent, symbol: string) => void;
  /** 沙盒手动市价进场（当前图表币种） */
  sandboxEnabled?: boolean;
  manualEnterBusy?: boolean;
  onManualEnter?: (args: {
    symbol: string;
    logic: "S" | "T";
    side: "LONG" | "SHORT";
  }) => void;
}

type ChartLayers = {
  bb: boolean;
  volume: boolean;
  macd: boolean;
  candlePattern: boolean;
};

const DEFAULT_LAYERS: ChartLayers = {
  bb: true,
  volume: true,
  macd: true,
  candlePattern: true,
};

const LAYER_TOGGLES: { key: keyof ChartLayers; label: string }[] = [
  { key: "bb", label: "布林" },
  { key: "volume", label: "量能" },
  { key: "macd", label: "MACD" },
  { key: "candlePattern", label: "射击/倒锤" },
];

const MARKER_LEGEND = [
  { kind: "h_max", label: "① H_max 绝对高点", color: "#ff5252" },
  { kind: "lh", label: "② LH 次高点", color: "#ffc107" },
  { kind: "l1", label: "L₁ 洗盘低点", color: "#ff8a80" },
  { kind: "hl", label: "③ HL 更高低点", color: "#00e676" },
  { kind: "mid_peak", label: "夹角反弹高点", color: "#64b5f6" },
  { kind: "trigger", label: "扳机线", color: "#64b5f6" },
  { kind: "hh", label: "④ HH 更高高点", color: "#00e676" },
  { kind: "bb_wick", label: "BB-Wicks 插针", color: "#e040fb" },
  { kind: "shooting_star", label: "射击之星", color: "#ff4081" },
  { kind: "inverted_hammer", label: "倒锤子", color: "#00bcd4" },
];

const VEGAS_SERIES: { key: VegasKey; title: string; color: string }[] = [
  { key: "filter", title: "过滤线 EMA12", color: "rgba(0, 230, 118, 0.85)" },
  { key: "a1", title: "A组1 EMA144", color: "rgba(33, 150, 243, 0.75)" },
  { key: "a2", title: "A组2 EMA169", color: "rgba(33, 150, 243, 0.45)" },
  { key: "b1", title: "B组1 EMA576", color: "rgba(239, 83, 80, 0.75)" },
  { key: "b2", title: "B组2 EMA676", color: "rgba(239, 83, 80, 0.45)" },
];

/** 射击之星 / 倒锤子：半尺寸箭头；字号随图表 layout.fontSize（整体 60%） */
const COMPACT_MARKER_KINDS = new Set(["shooting_star", "inverted_hammer"]);
const COMPACT_MARKER_SIZE = 0.5;
/** 图表全局字号 = LWC 默认 12 × 60% */
const CHART_FONT_SIZE = Math.round(12 * 0.6);

function toCandleMarkers(
  markers: PatternChartData["markers"],
  showCandlePattern: boolean,
): SeriesMarker<UTCTimestamp>[] {
  return [...(markers ?? [])]
    .filter((m) => showCandlePattern || !COMPACT_MARKER_KINDS.has(m.kind ?? ""))
    .sort((a, b) => a.time - b.time)
    .map((m) => {
      const kind = m.kind ?? "";
      const compact = COMPACT_MARKER_KINDS.has(kind);
      const fallback =
        kind === "shooting_star" ? "射击之星" : kind === "inverted_hammer" ? "倒锤子" : "";
      return {
        time: m.time as UTCTimestamp,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.text || fallback || undefined,
        size: compact ? COMPACT_MARKER_SIZE : 1,
      } as SeriesMarker<UTCTimestamp>;
    });
}

function toCandleData(candles: PatternCandle[]): CandlestickData[] {
  return candles.map((c) => ({
    time: c.time as UTCTimestamp,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));
}

function toVolumeData(candles: PatternCandle[]): HistogramData[] {
  return candles.map((c) => ({
    time: c.time as UTCTimestamp,
    value: c.volume ?? 0,
    // 半透明，叠在 K 线下沿时仍能看清影线/实体
    color: c.close >= c.open ? "rgba(0, 230, 118, 0.28)" : "rgba(255, 82, 82, 0.28)",
  }));
}

/** 量能柱从 0 起算，按当前可见区内最大量撑满分配高度 */
function volumeAutoscaleInfoProvider(
  original: () => { priceRange: { minValue: number; maxValue: number } | null } | null,
) {
  const res = original();
  if (!res?.priceRange) return res;
  const max = Math.max(res.priceRange.maxValue, 0);
  return {
    priceRange: {
      minValue: 0,
      // 略放大上限，避免最高柱贴顶；可视区内最高柱约占分配高度 ~85%
      maxValue: max <= 0 ? 1 : max / 0.85,
    },
  };
}

/** MACD 金叉/死叉小圆点（画在 DIF 线上） */
function buildMacdCrossMarkers(
  line: { time: number; value: number }[],
  signal: { time: number; value: number }[],
): SeriesMarker<UTCTimestamp>[] {
  const sigByTime = new Map(signal.map((p) => [p.time, p.value]));
  const markers: SeriesMarker<UTCTimestamp>[] = [];
  let prevDiff: number | null = null;

  for (const p of line) {
    const sig = sigByTime.get(p.time);
    if (sig == null || !Number.isFinite(p.value) || !Number.isFinite(sig)) {
      prevDiff = null;
      continue;
    }
    const diff = p.value - sig;
    if (prevDiff != null) {
      if (prevDiff <= 0 && diff > 0) {
        markers.push({
          time: p.time as UTCTimestamp,
          position: "inBar",
          shape: "circle",
          color: "#00e676",
          size: 0.6,
          text: undefined,
        });
      } else if (prevDiff >= 0 && diff < 0) {
        markers.push({
          time: p.time as UTCTimestamp,
          position: "inBar",
          shape: "circle",
          color: "#ff5252",
          size: 0.6,
          text: undefined,
        });
      }
    }
    prevDiff = diff;
  }
  return markers;
}

/** MACD 对称扩展，可见区内柱线充分利用分区高度 */
function macdAutoscaleInfoProvider(
  original: () => { priceRange: { minValue: number; maxValue: number } | null } | null,
) {
  const res = original();
  if (!res?.priceRange) return res;
  const { minValue, maxValue } = res.priceRange;
  const amp = Math.max(Math.abs(minValue), Math.abs(maxValue), 1e-12);
  return {
    priceRange: {
      minValue: -amp / 0.85,
      maxValue: amp / 0.85,
    },
  };
}

/**
 * 量能与 K 线共用主图区（同 bottom），叠在 K 线底部，不另开独立带。
 * 仅 MACD 在整图最底独占一条。
 */
function applyPaneMargins(chart: IChartApi, layers: ChartLayers) {
  const { volume, macd } = layers;
  const MACD_H = 0.24;
  // 量能相对「主图区」高度的占比（叠在底部，不上推 K 线）
  const VOL_IN_MAIN = 0.28;

  const mainBottom = macd ? MACD_H : 0.04;
  const mainTop = 0.03;
  // 主图区高度 → 量能从主图底部向上占 VOL_IN_MAIN
  const mainSpan = 1 - mainTop - mainBottom;
  const volTop = mainTop + mainSpan * (1 - (volume ? VOL_IN_MAIN : 0));

  // K 线始终铺满主图，不因量能上移留白
  chart.priceScale("right").applyOptions({
    scaleMargins: { top: mainTop, bottom: mainBottom },
  });

  if (volume) {
    chart.priceScale("volume").applyOptions({
      // 与 K 线同 bottom → 量能贴着主图底边叠画，而不是挤在中间另开一条
      scaleMargins: { top: volTop, bottom: mainBottom },
      borderVisible: false,
    });
  } else {
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.95, bottom: 0 },
      borderVisible: false,
    });
  }

  if (macd) {
    chart.priceScale("macd").applyOptions({
      scaleMargins: { top: 1 - MACD_H + 0.02, bottom: 0.02 },
      borderVisible: false,
    });
  } else {
    chart.priceScale("macd").applyOptions({
      scaleMargins: { top: 0.95, bottom: 0 },
      borderVisible: false,
    });
  }
}

export const PatternChartPanel = memo(function PatternChartPanel({
  symbol,
  state,
  liveTicker,
  onClose,
  onTitleContextMenu,
  sandboxEnabled = false,
  manualEnterBusy = false,
  onManualEnter,
}: Props) {
  const [manualLogic, setManualLogic] = useState<"S" | "T">("S");
  const [manualSide, setManualSide] = useState<"LONG" | "SHORT">("LONG");
  const chartRef = useRef<HTMLDivElement>(null);
  const crosshairPriceRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const upperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const midRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vegasRefs = useRef<Partial<Record<VegasKey, ISeriesApi<"Line">>>>({});
  const priceLinesRef = useRef<IPriceLine[]>([]);

  const candlesRef = useRef<PatternCandle[]>([]);
  const hasMoreRef = useRef(true);
  const loadingMoreRef = useRef(false);
  const timeframeRef = useRef<ChartTimeframe>("15m");
  const metaRef = useRef<PatternChartData | null>(null);
  const layersRef = useRef<ChartLayers>(DEFAULT_LAYERS);
  const priceDecimalsRef = useRef(2);
  const lastCloseRef = useRef(0);

  const [timeframe, setTimeframe] = useState<ChartTimeframe>("15m");
  const [data, setData] = useState<PatternChartData | null>(null);
  const [candleCount, setCandleCount] = useState(0);
  const [lastCandleTime, setLastCandleTime] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [err, setErr] = useState("");
  const [layers, setLayers] = useState<ChartLayers>(DEFAULT_LAYERS);
  layersRef.current = layers;

  const clearPriceLines = useCallback(() => {
    const series = seriesRef.current;
    if (!series) return;
    for (const line of priceLinesRef.current) {
      series.removePriceLine(line);
    }
    priceLinesRef.current = [];
  }, []);

  const applyPriceAxisFormat = useCallback((price: number | null | undefined) => {
    const fmt = chartPriceFormat(price);
    priceDecimalsRef.current = fmt.precision;
    seriesRef.current?.applyOptions({ priceFormat: fmt });
    upperRef.current?.applyOptions({ priceFormat: fmt });
    midRef.current?.applyOptions({ priceFormat: fmt });
    lowerRef.current?.applyOptions({ priceFormat: fmt });
    for (const { key } of VEGAS_SERIES) {
      vegasRefs.current[key]?.applyOptions({ priceFormat: fmt });
    }
    chartApi.current?.applyOptions({
      localization: {
        ...chartLocalization,
        priceFormatter: (p: number) => formatChartAxisPrice(p, priceDecimalsRef.current),
      },
    });
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

        const showPattern = layersRef.current.candlePattern;
        const rawMarkers = payload.partial ? metaRef.current?.markers : payload.markers;
        const markers = toCandleMarkers(rawMarkers, showPattern);
        if (markers.length) {
          series.setMarkers(markers);
        } else if (!payload.partial || !showPattern) {
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
        if (midRef.current) {
          const midPts = [...(payload.bb?.mid ?? [])].sort((a, b) => a.time - b.time);
          midRef.current.setData(
            midPts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) as LineData[],
          );
        }
        if (lowerRef.current) {
          const lowerPts = [...(payload.bb?.lower ?? [])].sort((a, b) => a.time - b.time);
          lowerRef.current.setData(
            lowerPts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) as LineData[],
          );
        }

        for (const { key } of VEGAS_SERIES) {
          const line = vegasRefs.current[key];
          if (!line) continue;
          const pts = [...(payload.vegas?.[key] ?? [])].sort((a, b) => a.time - b.time);
          line.setData(
            pts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) as LineData[],
          );
        }

        if (volumeRef.current) {
          volumeRef.current.setData(toVolumeData(sortedCandles));
        }

        if (macdHistRef.current) {
          const hist = [...(payload.macd?.hist ?? [])].sort((a, b) => a.time - b.time);
          macdHistRef.current.setData(
            hist.map(
              (p) =>
                ({
                  time: p.time as UTCTimestamp,
                  value: p.value,
                  color:
                    p.value >= 0 ? "rgba(0, 230, 118, 0.55)" : "rgba(255, 82, 82, 0.55)",
                }) as HistogramData,
            ),
          );
        }
        const macdLinePts = [...(payload.macd?.line ?? [])].sort((a, b) => a.time - b.time);
        const macdSigPts = [...(payload.macd?.signal ?? [])].sort((a, b) => a.time - b.time);
        if (macdLineRef.current) {
          macdLineRef.current.setData(
            macdLinePts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) as LineData[],
          );
          if (layersRef.current.macd) {
            macdLineRef.current.setMarkers(buildMacdCrossMarkers(macdLinePts, macdSigPts));
          } else {
            macdLineRef.current.setMarkers([]);
          }
        }
        if (macdSignalRef.current) {
          macdSignalRef.current.setData(
            macdSigPts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) as LineData[],
          );
        }

        applyPaneMargins(chart, layersRef.current);

        candlesRef.current = sortedCandles;
        setCandleCount(sortedCandles.length);
        setLastCandleTime(sortedCandles.at(-1)?.time ?? null);
        const close = sortedCandles.at(-1)?.close;
        if (close != null) applyPriceAxisFormat(close);

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
    [applyPriceLines, applyPriceAxisFormat],
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
      const mergedMid = mergeBbSeries(metaRef.current?.bb?.mid ?? [], chunk.bb?.mid ?? []);
      const mergedLower = mergeBbSeries(metaRef.current?.bb?.lower ?? [], chunk.bb?.lower ?? []);
      const mergedVegas = mergeVegasMap(metaRef.current?.vegas, chunk.vegas);
      const mergedMacd = mergeMacdMap(metaRef.current?.macd, chunk.macd);
      if (metaRef.current) {
        metaRef.current = {
          ...metaRef.current,
          bb: { upper: mergedUpper, mid: mergedMid, lower: mergedLower },
          vegas: mergedVegas,
          macd: mergedMacd,
        };
      }
      applyChartSeries(
        {
          ...chunk,
          partial: true,
          bb: { upper: mergedUpper, mid: mergedMid, lower: mergedLower },
          vegas: mergedVegas,
          macd: mergedMacd,
        },
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
      const mergedMid = mergeBbSeries(metaRef.current?.bb?.mid ?? [], json.bb?.mid ?? []);
      const mergedLower = mergeBbSeries(metaRef.current?.bb?.lower ?? [], json.bb?.lower ?? []);
      const mergedVegas = mergeVegasMap(metaRef.current?.vegas, json.vegas);
      const mergedMacd = mergeMacdMap(metaRef.current?.macd, json.macd);

      setData({
        ...json,
        candles: merged,
        bb: { upper: mergedUpper, mid: mergedMid, lower: mergedLower },
        vegas: mergedVegas,
        macd: mergedMacd,
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

      if (volumeRef.current && candle.volume != null) {
        volumeRef.current.update({
          time: candle.time as UTCTimestamp,
          value: candle.volume,
          color:
            candle.close >= candle.open
              ? "rgba(0, 230, 118, 0.28)"
              : "rgba(255, 82, 82, 0.28)",
        });
      }

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

  const applyLayerVisibility = useCallback((next: ChartLayers) => {
    const chart = chartApi.current;
    upperRef.current?.applyOptions({ visible: next.bb });
    midRef.current?.applyOptions({ visible: next.bb });
    lowerRef.current?.applyOptions({ visible: next.bb });
    volumeRef.current?.applyOptions({ visible: next.volume });
    macdHistRef.current?.applyOptions({ visible: next.macd });
    macdLineRef.current?.applyOptions({ visible: next.macd });
    macdSignalRef.current?.applyOptions({ visible: next.macd });
    if (macdLineRef.current) {
      if (next.macd && metaRef.current?.macd) {
        macdLineRef.current.setMarkers(
          buildMacdCrossMarkers(metaRef.current.macd.line ?? [], metaRef.current.macd.signal ?? []),
        );
      } else {
        macdLineRef.current.setMarkers([]);
      }
    }

    const series = seriesRef.current;
    if (series) {
      series.setMarkers(toCandleMarkers(metaRef.current?.markers, next.candlePattern));
    }

    if (chart) applyPaneMargins(chart, next);
  }, []);

  const toggleLayer = useCallback(
    (key: keyof ChartLayers) => {
      setLayers((prev) => {
        const next = { ...prev, [key]: !prev[key] };
        layersRef.current = next;
        applyLayerVisibility(next);
        return next;
      });
    },
    [applyLayerVisibility],
  );

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
      midRef.current = null;
      lowerRef.current = null;
      volumeRef.current = null;
      macdHistRef.current = null;
      macdLineRef.current = null;
      macdSignalRef.current = null;
      vegasRefs.current = {};
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
          fontSize: CHART_FONT_SIZE,
        },
        grid: {
          vertLines: { color: "#1e1e1e" },
          horzLines: { color: "#1e1e1e" },
        },
        rightPriceScale: { borderColor: "#2a2a2a" },
        localization: {
          ...chartLocalization,
          priceFormatter: (p: number) => formatChartAxisPrice(p, priceDecimalsRef.current),
        },
        timeScale: {
          borderColor: "#2a2a2a",
          ...chartTimeScaleOptions,
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          horzLine: { labelVisible: false },
        },
        handleScale: {
          axisPressedMouseMove: { time: true, price: true },
          mouseWheel: true,
          pinch: true,
        },
      });

      const seedFmt = chartPriceFormat(null);
      priceDecimalsRef.current = seedFmt.precision;

      const series = chart.addCandlestickSeries({
        upColor: "#00e676",
        downColor: "#ff5252",
        borderVisible: false,
        wickUpColor: "#00e676",
        wickDownColor: "#ff5252",
        priceFormat: seedFmt,
      });

      upperRef.current = chart.addLineSeries({
        color: "rgba(100, 181, 246, 0.45)",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        visible: layersRef.current.bb,
        priceFormat: seedFmt,
      });
      midRef.current = chart.addLineSeries({
        color: "rgba(255, 193, 7, 0.55)",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        visible: layersRef.current.bb,
        priceFormat: seedFmt,
      });
      lowerRef.current = chart.addLineSeries({
        color: "rgba(100, 181, 246, 0.25)",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        visible: layersRef.current.bb,
        priceFormat: seedFmt,
      });

      for (const { key, color } of VEGAS_SERIES) {
        vegasRefs.current[key] = chart.addLineSeries({
          color,
          lineWidth: key === "filter" ? 2 : 1,
          priceLineVisible: false,
          lastValueVisible: false,
          priceFormat: seedFmt,
        });
      }

      volumeRef.current = chart.addHistogramSeries({
        priceScaleId: "volume",
        priceFormat: { type: "volume" },
        priceLineVisible: false,
        lastValueVisible: false,
        visible: layersRef.current.volume,
        autoscaleInfoProvider: volumeAutoscaleInfoProvider,
      });

      macdHistRef.current = chart.addHistogramSeries({
        priceScaleId: "macd",
        priceLineVisible: false,
        lastValueVisible: false,
        visible: layersRef.current.macd,
        autoscaleInfoProvider: macdAutoscaleInfoProvider,
      });
      macdLineRef.current = chart.addLineSeries({
        priceScaleId: "macd",
        color: "rgba(33, 150, 243, 0.9)",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        visible: layersRef.current.macd,
        autoscaleInfoProvider: macdAutoscaleInfoProvider,
      });
      macdSignalRef.current = chart.addLineSeries({
        priceScaleId: "macd",
        color: "rgba(255, 152, 0, 0.9)",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        visible: layersRef.current.macd,
        autoscaleInfoProvider: macdAutoscaleInfoProvider,
      });

      applyPaneMargins(chart, layersRef.current);

      chartApi.current = chart;
      seriesRef.current = series;

      const hideCrosshairPrice = () => {
        const label = crosshairPriceRef.current;
        if (label) label.style.display = "none";
      };

      const onCrosshairMove = (param: {
        point?: { x: number; y: number } | undefined;
        time?: unknown;
      }) => {
        const label = crosshairPriceRef.current;
        const seriesApi = seriesRef.current;
        if (!label || !seriesApi) return;
        if (
          !param.point ||
          param.time === undefined ||
          param.point.x < 0 ||
          param.point.y < 0
        ) {
          hideCrosshairPrice();
          return;
        }
        const price = seriesApi.coordinateToPrice(param.point.y);
        if (price == null || !Number.isFinite(price)) {
          hideCrosshairPrice();
          return;
        }
        const d = priceDecimalsRef.current;
        const priceStr = d <= 0 ? String(Math.round(price)) : price.toFixed(d);
        const last = lastCloseRef.current;
        if (last > 0) {
          const pctChg = ((price - last) / last) * 100;
          const sign = pctChg >= 0 ? "+" : "";
          label.textContent = `${priceStr} (${sign}${pctChg.toFixed(2)}%)`;
          label.classList.toggle("pos", pctChg >= 0);
          label.classList.toggle("neg", pctChg < 0);
        } else {
          label.textContent = priceStr;
          label.classList.remove("pos", "neg");
        }
        label.style.display = "block";
        label.style.top = `${param.point.y}px`;
      };
      chart.subscribeCrosshairMove(onCrosshairMove);

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
        chart.unsubscribeCrosshairMove(onCrosshairMove);
        hideCrosshairPrice();
        chart.remove();
        chartApi.current = null;
        seriesRef.current = null;
        upperRef.current = null;
        midRef.current = null;
        lowerRef.current = null;
        volumeRef.current = null;
        macdHistRef.current = null;
        macdLineRef.current = null;
        macdSignalRef.current = null;
        vegasRefs.current = {};
        priceLinesRef.current = [];
      };
    } catch (e) {
      setErr(e instanceof Error ? e.message : "图表初始化失败");
    }
  }, [symbol, timeframe, loadMoreHistory]);

  useEffect(() => {
    if (!data?.candles?.length || !seriesRef.current) return;
    applyChartSeries(data, data.candles);
    applyLayerVisibility(layersRef.current);
  }, [data, applyChartSeries, applyLayerVisibility]);

  const analysis = data?.analysis;
  const ticker = data?.ticker;
  const lastPrice =
    markPrice ?? liveTicker?.last_price ?? ticker?.last_price ?? analysis?.last_price;
  const pct = liveTicker?.price_change_pct_24h ?? ticker?.price_change_pct_24h;
  const oiUsd = liveTicker?.current_oi_usd ?? ticker?.current_oi_usd;
  const quoteVol = liveTicker?.quote_volume ?? ticker?.quote_volume;
  const statusLabel = analysis?.status_label || state?.status_label || "—";

  useEffect(() => {
    const seed =
      lastPrice ??
      candlesRef.current.at(-1)?.close ??
      data?.candles?.at(-1)?.close ??
      0;
    if (seed && Number.isFinite(seed) && seed > 0) {
      lastCloseRef.current = Number(seed);
    }
  }, [lastPrice, data?.candles, candleCount]);

  useEffect(() => {
    if (!seriesRef.current) return;
    const seed =
      lastPrice ??
      candlesRef.current.at(-1)?.close ??
      data?.candles?.at(-1)?.close ??
      null;
    applyPriceAxisFormat(seed);
  }, [lastPrice, data?.candles, applyPriceAxisFormat]);

  const activeKinds = new Set(data?.markers?.map((m) => m.kind).filter(Boolean) ?? []);
  data?.price_lines?.forEach((l) => activeKinds.add(l.kind));
  const hasVegas = Boolean(
    data?.vegas && VEGAS_SERIES.some((s) => (data.vegas?.[s.key]?.length ?? 0) > 0),
  );

  return (
    <div className="pattern-chart-panel">
      <header className="pattern-chart-head">
        <div className="pattern-chart-head-top">
          <div
            className="pattern-chart-title"
            title={onTitleContextMenu ? "右键可置顶（至少 1 天）或取消置顶" : undefined}
            onContextMenu={(e) => onTitleContextMenu?.(e, symbol)}
          >
            <span className="coin-avatar">{coinInitial(symbol)}</span>
            <div>
              <h2>${displaySymbol(symbol)}</h2>
              <div className="pattern-chart-meta">
                <span className={pct != null && pct >= 0 ? "pos" : "neg"}>
                  ${fmtMetaPrice(lastPrice)}
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
            <div className="pattern-chart-layers" role="group" aria-label="图表图层">
              {LAYER_TOGGLES.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  className={`layer-btn ${layers[key] ? "active" : ""}`}
                  onClick={() => toggleLayer(key)}
                  title={layers[key] ? `隐藏${label}` : `显示${label}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <button type="button" className="pattern-chart-close" onClick={onClose}>
              返回列表
            </button>
          </div>
        </div>
        {sandboxEnabled && onManualEnter ? (
          <div className="sandbox-manual chart-head">
            <span className="sandbox-manual-label">手动市价进场 · ${displaySymbol(symbol)}</span>
            <select
              value={manualLogic}
              onChange={(e) => setManualLogic(e.target.value as "S" | "T")}
              disabled={manualEnterBusy}
              aria-label="逻辑"
            >
              <option value="S">S · 短线猎手</option>
              <option value="T">T · 长线维加斯</option>
            </select>
            <select
              value={manualSide}
              onChange={(e) => setManualSide(e.target.value as "LONG" | "SHORT")}
              disabled={manualEnterBusy}
              aria-label="方向"
            >
              <option value="LONG">做多 LONG</option>
              <option value="SHORT">做空 SHORT</option>
            </select>
            <button
              type="button"
              className="pattern-random-btn"
              disabled={manualEnterBusy}
              onClick={() =>
                onManualEnter({ symbol, logic: manualLogic, side: manualSide })
              }
            >
              市价开仓
            </button>
          </div>
        ) : null}
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
                {hasVegas
                  ? VEGAS_SERIES.map((s) => (
                      <li key={`vegas-${s.key}`}>
                        <span className="legend-dot" style={{ background: s.color }} />
                        Vegas {s.title}
                      </li>
                    ))
                  : null}
                {(data?.bb?.mid?.length ?? 0) > 0 ? (
                  <li key="bb-mid">
                    <span className="legend-dot" style={{ background: "rgba(255, 193, 7, 0.85)" }} />
                    布林中轨
                  </li>
                ) : null}
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
        <div className="pattern-chart-wrap">
          <div className="pattern-chart-canvas" ref={chartRef} />
          <div
            ref={crosshairPriceRef}
            className="pattern-crosshair-price"
            aria-hidden
          />
        </div>
      </div>
    </div>
  );
});
