import { memo, useEffect, useRef, useState } from "react";
import {
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PatternChartData, PatternState } from "../types";
import { fmtNum, fmtPct } from "../utils/format";
import { coinInitial, displaySymbol } from "../utils/symbol";

interface Props {
  symbol: string;
  state?: PatternState;
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

export const PatternChartPanel = memo(function PatternChartPanel({ symbol, state, onClose }: Props) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApi = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [data, setData] = useState<PatternChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr("");
    fetch(`/api/patterns/chart?symbol=${encodeURIComponent(symbol)}`)
      .then((r) => r.json())
      .then((json: PatternChartData) => {
        if (cancelled) return;
        if (!json.ok) {
          setErr(json.error || "加载失败");
          setData(null);
        } else {
          setData(json);
        }
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
  }, [symbol]);

  useEffect(() => {
    if (!chartRef.current || !data?.candles?.length) return;

    if (chartApi.current) {
      chartApi.current.remove();
      chartApi.current = null;
      seriesRef.current = null;
    }

    const candles = [...data.candles]
      .sort((a, b) => a.time - b.time)
      .filter((c, i, arr) => i === 0 || c.time !== arr[i - 1].time);

    try {
      const chart = createChart(chartRef.current, {
        width: chartRef.current.clientWidth,
        height: chartRef.current.clientHeight,
        layout: {
          background: { type: ColorType.Solid, color: "#0a0a0a" },
          textColor: "#9e9e9e",
        },
        grid: {
          vertLines: { color: "#1e1e1e" },
          horzLines: { color: "#1e1e1e" },
        },
        rightPriceScale: { borderColor: "#2a2a2a" },
        timeScale: { borderColor: "#2a2a2a", timeVisible: true },
        crosshair: { mode: 1 },
      });

      const series = chart.addCandlestickSeries({
        upColor: "#00e676",
        downColor: "#ff5252",
        borderVisible: false,
        wickUpColor: "#00e676",
        wickDownColor: "#ff5252",
      });

      series.setData(
        candles.map((c) => ({
          time: c.time as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        })) as CandlestickData[],
      );

      const markers = [...(data.markers ?? [])].sort((a, b) => a.time - b.time);
      if (markers.length) {
        series.setMarkers(
          markers.map((m) => ({
            time: m.time as UTCTimestamp,
            position: m.position,
            color: m.color,
            shape: m.shape,
            text: m.text,
          })),
        );
      }

      data.price_lines?.forEach((line) => {
        series.createPriceLine({
          price: line.price,
          color: line.color,
          lineWidth: 1,
          lineStyle: line.kind === "trigger" ? 2 : 0,
          axisLabelVisible: true,
          title: line.title,
        });
      });

      if (data.bb?.upper?.length) {
        const upper = chart.addLineSeries({
          color: "rgba(100, 181, 246, 0.45)",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        upper.setData(
          [...data.bb.upper]
            .sort((a, b) => a.time - b.time)
            .map((p) => ({ time: p.time as UTCTimestamp, value: p.value })),
        );
        const lower = chart.addLineSeries({
          color: "rgba(100, 181, 246, 0.25)",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        lower.setData(
          [...data.bb.lower]
            .sort((a, b) => a.time - b.time)
            .map((p) => ({ time: p.time as UTCTimestamp, value: p.value })),
        );
      }

      chart.timeScale().fitContent();
      chartApi.current = chart;
      seriesRef.current = series;

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
        chart.remove();
        chartApi.current = null;
        seriesRef.current = null;
      };
    } catch (e) {
      setErr(e instanceof Error ? e.message : "图表渲染失败");
    }
  }, [data]);

  const analysis = data?.analysis;
  const ticker = data?.ticker;
  const pct = ticker?.price_change_pct_24h;
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
                ${ticker?.last_price?.toPrecision(5) ?? analysis?.last_price?.toPrecision(5) ?? "—"}
                {pct != null ? ` · ${fmtPct(pct)}` : ""}
              </span>
              <span>OI {fmtNum(ticker?.current_oi_usd)}</span>
              <span>24h额 {fmtNum(ticker?.quote_volume)}</span>
              <span className="pat-status-tag">{statusLabel}</span>
            </div>
          </div>
        </div>
        <button type="button" className="pattern-chart-close" onClick={onClose}>
          返回列表
        </button>
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
              <p className="pattern-interval-tag">{data?.interval ?? "15m"} · 合约永续</p>
            </>
          )}
        </aside>
        <div className="pattern-chart-wrap" ref={chartRef} />
      </div>
    </div>
  );
});
