import { memo, useCallback, useState } from "react";
import type { PatternAlert, PatternState, PatternWatchItem } from "../types";
import { coinInitial, displaySymbol } from "../utils/symbol";
import { MercuHeader } from "../components/MercuHeader";
import { PatternChartPanel } from "../components/PatternChartPanel";
import { PatternToastStack } from "../components/PatternToastStack";
import { useRadarSSE } from "../hooks/useRadarSSE";

const STATUS_CLASS: Record<string, string> = {
  SEARCHING_TOP: "pat-search",
  STAGE_1_LH_DETECTED: "pat-lh",
  WAITING_FOR_HL: "pat-wait",
  TRIGGER_SIGNAL: "pat-fire",
  EXPIRED: "pat-expired",
};

export const PatternMonitorPage = memo(function PatternMonitorPage() {
  const { snapshot, online } = useRadarSSE();
  const pattern = snapshot.pattern;
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  const watchlist: PatternWatchItem[] = pattern?.watchlist ?? [];
  const states: PatternState[] = pattern?.states ?? [];
  const alerts: PatternAlert[] = pattern?.pattern_alerts ?? [];
  const scanTs = pattern?.scan_ts ?? snapshot.scan_ts;

  const addSymbol = useCallback(async () => {
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    setBusy(true);
    setErr("");
    try {
      const res = await fetch("/api/patterns/watch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym }),
      });
      const data = await res.json();
      if (!data.ok) setErr(data.error || "添加失败");
      else {
        setInput("");
        setSelectedSymbol(sym);
      }
    } catch {
      setErr("网络错误");
    } finally {
      setBusy(false);
    }
  }, [input]);

  const removeSymbol = useCallback(async (symbol: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setBusy(true);
    try {
      await fetch(`/api/patterns/watch?symbol=${encodeURIComponent(symbol)}`, {
        method: "DELETE",
      });
      if (selectedSymbol === symbol) setSelectedSymbol(null);
    } finally {
      setBusy(false);
    }
  }, [selectedSymbol]);

  const randomPick = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      const res = await fetch("/api/patterns/random", { method: "POST" });
      const data = await res.json();
      if (!data.ok) setErr(data.error || "随机挑选失败");
      else setSelectedSymbol(null);
    } catch {
      setErr("网络错误");
    } finally {
      setBusy(false);
    }
  }, []);

  const autoPickCount = pattern?.auto_pick_count ?? 20;
  const heavyPool = pattern?.heavyweight_pool_size ?? 0;
  const selectedState = states.find((s) => s.symbol === selectedSymbol);
  const selectedTicker = selectedSymbol
    ? snapshot.all_tickers.find((t) => t.symbol === selectedSymbol)
    : undefined;

  return (
    <div className="mercu-app pattern-app">
      <MercuHeader
        online={online}
        scanTs={scanTs}
        poolMeta={snapshot.pool_meta}
        poolSize={snapshot.pool_size}
      />

      <div className="pattern-layout">
        <aside className="pattern-sidebar panel">
          <h2>形态追踪</h2>
          <p className="pattern-desc">
            启动时从大象池（≥5000万 OI）随机挑选 {autoPickCount} 个币种 · 点击币种查看 K 线标注
          </p>

          <div className="pattern-toolbar">
            <button type="button" className="pattern-random-btn" onClick={randomPick} disabled={busy}>
              大象随机重选
            </button>
            <span className="pattern-pool-hint">大象池 {heavyPool} 个</span>
          </div>

          <div className="pattern-add">
            <input
              type="text"
              placeholder="如 BTCUSDT"
              value={input}
              onChange={(e) => setInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && addSymbol()}
              disabled={busy}
            />
            <button type="button" onClick={addSymbol} disabled={busy || !input.trim()}>
              添加
            </button>
          </div>
          {err && <p className="pattern-err">{err}</p>}
          <p className="pattern-meta">已监听 {watchlist.length} / 30（可手动追加）</p>

          <ul className="pattern-watchlist">
            {watchlist.length === 0 ? (
              <li className="pattern-empty">等待雷达扫描后自动从大象池随机挑选…</li>
            ) : (
              watchlist.map((w) => {
                const st = states.find((s) => s.symbol === w.symbol);
                const cls = STATUS_CLASS[st?.status ?? "SEARCHING_TOP"] ?? "pat-search";
                const active = selectedSymbol === w.symbol;
                return (
                  <li
                    key={w.symbol}
                    className={`pattern-watch-item ${cls}${active ? " active" : ""}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedSymbol(w.symbol)}
                    onKeyDown={(e) => e.key === "Enter" && setSelectedSymbol(w.symbol)}
                  >
                    <div className="pattern-watch-head">
                      <span className="coin-avatar sm">{coinInitial(w.symbol)}</span>
                      <span className="pattern-sym">${displaySymbol(w.symbol)}</span>
                      <button
                        type="button"
                        className="pattern-rm"
                        onClick={(e) => removeSymbol(w.symbol, e)}
                        disabled={busy}
                        aria-label="移除"
                      >
                        ×
                      </button>
                    </div>
                    <div className="pattern-status">{st?.status_label ?? "寻找顶部"}</div>
                    {st?.message && <div className="pattern-msg">{st.message}</div>}
                    {st && (st.lh_price ?? 0) > 0 && (
                      <div className="pattern-levels">
                        <span>LH {st.lh_price!.toPrecision(4)}</span>
                        {(st.hl ?? 0) > 0 && <span>HL {st.hl!.toPrecision(4)}</span>}
                        {(st.trigger_price ?? 0) > 0 && <span>扳机 {st.trigger_price!.toPrecision(4)}</span>}
                      </div>
                    )}
                  </li>
                );
              })
            )}
          </ul>
        </aside>

        <main className="pattern-main panel">
          {selectedSymbol ? (
            <PatternChartPanel
              symbol={selectedSymbol}
              state={selectedState}
              liveTicker={selectedTicker}
              onClose={() => setSelectedSymbol(null)}
            />
          ) : (
            <>
              <div className="pattern-main-head">
                <h2>形态预警流</h2>
                <span className="pattern-scan">
                  最近扫描 {scanTs ? new Date(scanTs * 1000).toLocaleTimeString("zh-CN") : "—"}
                </span>
              </div>
              <p className="pattern-hint-main">← 点击左侧币种查看 15m K 线与形态拐点标注</p>

              <div className="pattern-flow">
                {states.filter((s) => s.status === "STAGE_1_LH_DETECTED" || s.status === "WAITING_FOR_HL").length > 0 && (
                  <section className="pattern-section">
                    <h3>观察中</h3>
                    <ul>
                      {states
                        .filter((s) => s.status === "STAGE_1_LH_DETECTED" || s.status === "WAITING_FOR_HL")
                        .map((s) => (
                          <li
                            key={s.symbol}
                            className="pattern-flow-item watch clickable"
                            role="button"
                            tabIndex={0}
                            onClick={() => setSelectedSymbol(s.symbol)}
                            onKeyDown={(e) => e.key === "Enter" && setSelectedSymbol(s.symbol)}
                          >
                            <strong>${displaySymbol(s.symbol)}</strong>
                            <span>{s.status_label}</span>
                            <em>{s.message}</em>
                          </li>
                        ))}
                    </ul>
                  </section>
                )}

                <section className="pattern-section">
                  <h3>扳机历史（本轮）</h3>
                  <ul>
                    {alerts.length === 0 ? (
                      <li className="pattern-empty">暂无扳机信号，添加币种后自动扫描</li>
                    ) : (
                      alerts.map((a) => (
                        <li
                          key={`${a.symbol}-${a.kline_close_time}`}
                          className="pattern-flow-item fire clickable"
                          role="button"
                          tabIndex={0}
                          onClick={() => setSelectedSymbol(a.symbol)}
                          onKeyDown={(e) => e.key === "Enter" && setSelectedSymbol(a.symbol)}
                        >
                          <strong>${displaySymbol(a.symbol)}</strong>
                          <span className="pat-fire-tag">多头爆发</span>
                          <em>{a.message}</em>
                          <div className="pattern-levels inline">
                            <span>HL {a.hl.toPrecision(4)}</span>
                            <span>突破 {a.trigger_price.toPrecision(4)}</span>
                          </div>
                        </li>
                      ))
                    )}
                  </ul>
                </section>
              </div>
            </>
          )}
        </main>
      </div>

      <PatternToastStack alerts={alerts} scanTs={scanTs} />
    </div>
  );
});

