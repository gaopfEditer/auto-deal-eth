import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type { PatternAlert, PatternPayload, PatternState, PatternWatchItem } from "../types";
import { coinInitial, displaySymbol } from "../utils/symbol";
import { MercuHeader } from "../components/MercuHeader";
import { PatternChartPanel } from "../components/PatternChartPanel";
import { PatternToastStack } from "../components/PatternToastStack";
import { SandboxToastStack } from "../components/SandboxToastStack";
import { useRadarSSE } from "../hooks/useRadarSSE";
import { useSandboxTradeHistory } from "../hooks/useSandboxTradeHistory";
import { fmtMetaPrice, fmtTs } from "../utils/format";
import {
  filterHistoryByRange,
  SANDBOX_HISTORY_RANGE_OPTIONS,
  SANDBOX_HISTORY_RETAIN_DAYS,
  summarizeHistoryRange,
  type SandboxHistoryRange,
} from "../utils/sandboxHistory";

function fmtTradeEvents(events?: Array<Record<string, unknown>>, fallback?: string): string {
  if (!events?.length) return fallback?.trim() || "—";
  return events
    .filter((e) => e.type && e.type !== "sync")
    .map((e) => {
      const t =
        e.type === "entry"
          ? "入"
          : e.type === "exit"
            ? "出"
            : e.type === "partial"
              ? "减"
              : "移";
      const px = e.price != null ? fmtMetaPrice(Number(e.price)) : "";
      const sl = e.sl != null ? ` SL${fmtMetaPrice(Number(e.sl))}` : "";
      const extra =
        e.type === "exit" && e.exit_label
          ? ` ${String(e.exit_label)}`
          : e.message
            ? ` ${String(e.message)}`
            : "";
      return `${t}@${px}${sl}${extra}`.replace(/\s+/g, " ").trim();
    })
    .filter(Boolean)
    .join("; ");
}

const STATUS_CLASS: Record<string, string> = {
  SEARCHING_TOP: "pat-search",
  STAGE_1_LH_DETECTED: "pat-lh",
  WAITING_FOR_HL: "pat-wait",
  TRIGGER_SIGNAL: "pat-fire",
  EXPIRED: "pat-expired",
};

export const PatternMonitorPage = memo(function PatternMonitorPage() {
  const { snapshot, online, patchPattern } = useRadarSSE();
  const pattern = snapshot.pattern;
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [mainTab, setMainTab] = useState<"pattern" | "sandbox">("pattern");
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; symbol: string } | null>(null);

  const watchlist: PatternWatchItem[] = pattern?.watchlist ?? [];
  const states: PatternState[] = pattern?.states ?? [];
  const alerts: PatternAlert[] = pattern?.pattern_alerts ?? [];
  const sandboxAlerts: PatternAlert[] = pattern?.sandbox_alerts ?? [];
  const sandboxPool = pattern?.sandbox_pool ?? [];
  const sandboxPositions = pattern?.sandbox_positions ?? [];
  const sandboxStats = pattern?.sandbox_stats;
  const scanTs = pattern?.scan_ts ?? snapshot.scan_ts;
  const sandboxScanTs = pattern?.sandbox_scan_ts ?? scanTs;
  const sandboxExitAlerts = useMemo(
    () => sandboxAlerts.filter((a) => a.type === "exit"),
    [sandboxAlerts],
  );
  const watchingStates = useMemo(
    () =>
      states.filter(
        (s) => s.status === "STAGE_1_LH_DETECTED" || s.status === "WAITING_FOR_HL",
      ),
    [states],
  );
  const sandboxOn = pattern?.sandbox_enabled !== false;
  const sandboxMaxConcurrent = pattern?.sandbox_max_concurrent ?? 10;
  const enteredSymbols = useMemo(() => {
    const set = new Set<string>();
    for (const p of sandboxPositions) {
      const s = String(p.symbol || "").trim().toUpperCase();
      if (s) set.add(s);
    }
    return set;
  }, [sandboxPositions]);

  /** 左侧列表：置顶 → 进行中持仓 → 其余（组内保持原相对顺序） */
  const sortedWatchlist = useMemo(() => {
    const pinned: PatternWatchItem[] = [];
    const trading: PatternWatchItem[] = [];
    const rest: PatternWatchItem[] = [];
    for (const w of watchlist) {
      const sym = String(w.symbol || "").trim().toUpperCase();
      if (w.pinned) pinned.push(w);
      else if (enteredSymbols.has(sym)) trading.push(w);
      else rest.push(w);
    }
    return [...pinned, ...trading, ...rest];
  }, [watchlist, enteredSymbols]);

  const [manualSym, setManualSym] = useState("");
  const [manualLogic, setManualLogic] = useState<"S" | "T">("S");
  const [manualSide, setManualSide] = useState<"LONG" | "SHORT">("LONG");
  const [manualInterval, setManualInterval] = useState<"15m" | "1h">("15m");
  /** 持仓手动平仓百分比，key=position id */
  const [closePctById, setClosePctById] = useState<Record<number, number>>({});
  const [closingId, setClosingId] = useState<number | null>(null);
  const [historyRange, setHistoryRange] = useState<SandboxHistoryRange>("7d");
  const [sandboxFilter, setSandboxFilter] = useState<"all" | "st" | "card">("all");
  const sandboxIntervals = useMemo(() => {
    const raw = pattern?.sandbox_intervals;
    if (Array.isArray(raw) && raw.length) {
      return raw.map(String).filter((x) => x === "15m" || x === "1h") as Array<"15m" | "1h">;
    }
    return ["15m", "1h"] as Array<"15m" | "1h">;
  }, [pattern?.sandbox_intervals]);

  const sandboxHistory = useSandboxTradeHistory({
    recentTrades: sandboxStats?.recent_trades,
    historyTrades: pattern?.sandbox_trade_history,
    day: sandboxStats?.day,
    exitAlerts: sandboxExitAlerts,
    scanTs: sandboxScanTs,
  });
  const filteredHistory = useMemo(() => {
    const byRange = filterHistoryByRange(sandboxHistory, historyRange);
    if (sandboxFilter === "card") {
      return byRange.filter(
        (t) => t.logic === "C" || t.source === "card" || t.source_label === "卡片",
      );
    }
    if (sandboxFilter === "st") {
      return byRange.filter(
        (t) => t.logic !== "C" && t.source !== "card" && t.source_label !== "卡片",
      );
    }
    return byRange;
  }, [sandboxHistory, historyRange, sandboxFilter]);
  const historyRangeStats = useMemo(
    () => summarizeHistoryRange(filteredHistory),
    [filteredHistory],
  );
  const filteredPositions = useMemo(() => {
    if (sandboxFilter === "card") {
      return sandboxPositions.filter(
        (p) => p.logic === "C" || p.source === "card" || p.source_label === "卡片",
      );
    }
    if (sandboxFilter === "st") {
      return sandboxPositions.filter(
        (p) => p.logic !== "C" && p.source !== "card" && p.source_label !== "卡片",
      );
    }
    return sandboxPositions;
  }, [sandboxPositions, sandboxFilter]);
  const cardOrders = pattern?.sandbox_card_orders ?? [];
  const filteredCardOrders = useMemo(() => {
    if (sandboxFilter === "st") return [];
    return cardOrders.filter((o) =>
      ["watching", "near", "ordered", "filled"].includes(o.status),
    );
  }, [cardOrders, sandboxFilter]);

  const reshuffleSandbox = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      const res = await fetch("/api/sandbox/reshuffle", { method: "POST" });
      const data = await res.json();
      if (!data.ok) setErr(data.error || "沙盒日池重抽失败");
    } catch {
      setErr("网络错误");
    } finally {
      setBusy(false);
    }
  }, []);

  const manualSandboxEnter = useCallback(
    async (args?: {
      symbol?: string;
      logic?: "S" | "T";
      side?: "LONG" | "SHORT";
      interval?: "15m" | "1h";
    }) => {
      const sym = (args?.symbol || manualSym || selectedSymbol || "").trim().toUpperCase();
      const logic = args?.logic || manualLogic;
      const side = args?.side || manualSide;
      const interval = args?.interval || manualInterval;
      if (!sym) {
        setErr("请填写或选中币种");
        return;
      }
      setBusy(true);
      setErr("");
      try {
        const res = await fetch("/api/sandbox/enter", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ symbol: sym, logic, side, interval }),
        });
        const data = await res.json();
        if (!data.ok) setErr(data.error || "市价开仓失败");
        else {
          setMainTab("sandbox");
          setSelectedSymbol(sym);
          // 立刻同步持仓到左侧列表高亮（不必等下一轮 SSE）
          const patch: Partial<PatternPayload> = {};
          if (Array.isArray(data.sandbox_positions)) {
            patch.sandbox_positions = data.sandbox_positions;
          }
          if (data.sandbox_stats) patch.sandbox_stats = data.sandbox_stats;
          if (Array.isArray(data.sandbox_pool)) patch.sandbox_pool = data.sandbox_pool;
          if (Array.isArray(data.sandbox_alerts)) patch.sandbox_alerts = data.sandbox_alerts;
          if (Object.keys(patch).length) patchPattern(patch);
        }
      } catch {
        setErr("网络错误");
      } finally {
        setBusy(false);
      }
    },
    [manualSym, selectedSymbol, manualLogic, manualSide, manualInterval, patchPattern],
  );

  const manualSandboxClose = useCallback(
    async (positionId: number, pct: number) => {
      if (!positionId) {
        setErr("缺少持仓 ID");
        return;
      }
      const p = Math.min(100, Math.max(1, Math.round(Number(pct) || 100)));
      setClosingId(positionId);
      setBusy(true);
      setErr("");
      try {
        const res = await fetch("/api/sandbox/close", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ position_id: positionId, pct: p }),
        });
        const data = await res.json();
        if (!data.ok) setErr(data.error || "平仓失败");
        else {
          const patch: Partial<PatternPayload> = {};
          if (Array.isArray(data.sandbox_positions)) {
            patch.sandbox_positions = data.sandbox_positions;
          }
          if (data.sandbox_stats) patch.sandbox_stats = data.sandbox_stats;
          if (Array.isArray(data.sandbox_trade_history)) {
            patch.sandbox_trade_history = data.sandbox_trade_history;
          }
          if (Array.isArray(data.sandbox_alerts)) patch.sandbox_alerts = data.sandbox_alerts;
          if (Array.isArray(data.sandbox_card_orders)) {
            patch.sandbox_card_orders = data.sandbox_card_orders;
          }
          if (Object.keys(patch).length) patchPattern(patch);
        }
      } catch {
        setErr("网络错误");
      } finally {
        setBusy(false);
        setClosingId(null);
      }
    },
    [patchPattern],
  );

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
        if (Array.isArray(data.watchlist)) {
          patchPattern({ watchlist: data.watchlist });
        }
      }
    } catch {
      setErr("网络错误");
    } finally {
      setBusy(false);
    }
  }, [input, patchPattern]);

  const removeSymbol = useCallback(async (symbol: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setBusy(true);
    setErr("");
    try {
      const res = await fetch(`/api/patterns/watch?symbol=${encodeURIComponent(symbol)}`, {
        method: "DELETE",
      });
      const data = await res.json();
      if (!data.ok) {
        setErr(data.error || "移除失败");
        return;
      }
      const nextWatch: PatternWatchItem[] = Array.isArray(data.watchlist)
        ? data.watchlist
        : watchlist.filter((w) => w.symbol !== symbol);
      patchPattern({
        watchlist: nextWatch,
        states: states.filter((s) => s.symbol !== symbol),
      });
      if (selectedSymbol === symbol) setSelectedSymbol(null);
    } catch {
      setErr("网络错误");
    } finally {
      setBusy(false);
    }
  }, [selectedSymbol, watchlist, states, patchPattern]);

  const openWatchCtxMenu = useCallback((e: React.MouseEvent, symbol: string) => {
    e.preventDefault();
    e.stopPropagation();
    setCtxMenu({ x: e.clientX, y: e.clientY, symbol });
  }, []);

  const pinSymbolToTop = useCallback(async (symbol: string, pinned: boolean) => {
    setCtxMenu(null);
    setBusy(true);
    setErr("");
    try {
      const res = await fetch("/api/patterns/watch/pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, pinned }),
      });
      const data = await res.json();
      if (!data.ok) {
        setErr(data.error || (pinned ? "置顶失败" : "取消置顶失败"));
        return;
      }
      if (Array.isArray(data.watchlist)) {
        patchPattern({ watchlist: data.watchlist });
      }
    } catch {
      setErr("网络错误");
    } finally {
      setBusy(false);
    }
  }, [patchPattern]);

  const togglePin = useCallback(
    (symbol: string, currentlyPinned: boolean, e?: React.MouseEvent) => {
      e?.stopPropagation();
      e?.preventDefault();
      void pinSymbolToTop(symbol, !currentlyPinned);
    },
    [pinSymbolToTop],
  );

  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [ctxMenu]);

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
            每 {Math.round((pattern?.watchlist_refresh_sec ?? 7200) / 3600)} 小时用合约流入 + OI
            爆发刷新 {autoPickCount} 个；雷达「涨幅∩持仓」即时入池；已进场与沙盒持仓保留 ·
            点击查看 K 线
          </p>

          <div className="pattern-toolbar">
            <button type="button" className="pattern-random-btn" onClick={randomPick} disabled={busy}>
              热钱重选
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
          <p className="pattern-meta">
            已监听 {watchlist.length} / 30（排序：置顶 → 持仓 → 其他）
          </p>

          <ul className="pattern-watchlist">
            {sortedWatchlist.length === 0 ? (
              <li className="pattern-empty">等待雷达扫描后按合约流入 / OI 爆发自动挑选…</li>
            ) : (
              sortedWatchlist.map((w) => {
                const st = states.find((s) => s.symbol === w.symbol);
                const cls = STATUS_CLASS[st?.status ?? "SEARCHING_TOP"] ?? "pat-search";
                const active = selectedSymbol === w.symbol;
                const pinned = Boolean(w.pinned);
                const entered = enteredSymbols.has(String(w.symbol || "").trim().toUpperCase());
                const pinHours =
                  pinned && (w.pin_remaining_sec ?? 0) > 0
                    ? Math.max(1, Math.ceil((w.pin_remaining_sec ?? 0) / 3600))
                    : 0;
                return (
                  <li
                    key={w.symbol}
                    className={`pattern-watch-item ${cls}${active ? " active" : ""}${pinned ? " pinned" : ""}${entered ? " entered" : ""}`}
                    data-entered={entered ? "1" : undefined}
                    role="button"
                    tabIndex={0}
                    title={
                      entered
                        ? "沙盒持仓中"
                        : pinned
                          ? `已置顶，约剩 ${pinHours} 小时`
                          : "点击查看 K 线"
                    }
                    onClick={() => {
                      setSelectedSymbol(w.symbol);
                      setManualSym(w.symbol);
                    }}
                    onContextMenu={(e) => openWatchCtxMenu(e, w.symbol)}
                    onKeyDown={(e) => e.key === "Enter" && setSelectedSymbol(w.symbol)}
                  >
                    <div className="pattern-watch-head">
                      <span className="coin-avatar sm">{coinInitial(w.symbol)}</span>
                      <span className="pattern-sym">${displaySymbol(w.symbol)}</span>
                      {entered ? (
                        <span className="pattern-entered-badge" title="沙盒持仓中">
                          持仓
                        </span>
                      ) : null}
                      <button
                        type="button"
                        className={`pattern-pin-btn${pinned ? " on" : ""}`}
                        onClick={(e) => togglePin(w.symbol, pinned, e)}
                        disabled={busy}
                        title={
                          pinned
                            ? `已置顶${pinHours > 0 ? ` · 约剩 ${pinHours}h` : ""}，再点取消`
                            : "置顶至少 1 天"
                        }
                        aria-label={pinned ? "取消置顶" : "置顶"}
                        aria-pressed={pinned}
                      >
                        置顶
                      </button>
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
          <div className="pattern-main-head">
            <div className="pattern-main-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={mainTab === "pattern" && !selectedSymbol}
                className={`pattern-main-tab${mainTab === "pattern" && !selectedSymbol ? " active" : ""}`}
                onClick={() => {
                  setMainTab("pattern");
                  setSelectedSymbol(null);
                }}
              >
                形态预警流
                {(watchingStates.length > 0 || alerts.length > 0) && (
                  <em>{watchingStates.length + alerts.length}</em>
                )}
              </button>
              {sandboxOn && (
                <button
                  type="button"
                  role="tab"
                  aria-selected={mainTab === "sandbox" && !selectedSymbol}
                  className={`pattern-main-tab${mainTab === "sandbox" && !selectedSymbol ? " active" : ""}`}
                  onClick={() => {
                    setMainTab("sandbox");
                    setSelectedSymbol(null);
                  }}
                >
                  沙盒纸面交易
                  {sandboxPositions.length > 0 && <em>{sandboxPositions.length}</em>}
                </button>
              )}
            </div>
            <span className="pattern-scan">
              {selectedSymbol
                ? `K 线 · $${displaySymbol(selectedSymbol)}`
                : `最近扫描 ${scanTs ? new Date(scanTs * 1000).toLocaleTimeString("zh-CN") : "—"}`}
            </span>
          </div>

          {selectedSymbol ? (
            <PatternChartPanel
              symbol={selectedSymbol}
              state={selectedState}
              liveTicker={selectedTicker}
              onClose={() => setSelectedSymbol(null)}
              onTitleContextMenu={openWatchCtxMenu}
              sandboxEnabled={sandboxOn}
              manualEnterBusy={busy}
              onManualEnter={(args) => void manualSandboxEnter(args)}
            />
          ) : mainTab === "pattern" ? (
                <div className="pattern-flow pattern-tab-panel">
                  <div className="strategy-brief-grid">
                    <article className="strategy-brief">
                      <header>
                        <span className="strategy-brief-tag">阶段 1</span>
                        <strong>次高点 LH</strong>
                      </header>
                      <p>
                        两 pivot 高点形成后高 &lt; 前高 → LH / H_max；需 BB 上轨插针或 MACD 高位走弱确认。
                      </p>
                    </article>
                    <article className="strategy-brief">
                      <header>
                        <span className="strategy-brief-tag">阶段 2</span>
                        <strong>更高低点 HL</strong>
                      </header>
                      <p>
                        LH 之后出现 HL &gt; L₁；扳机线 = L₁～HL 区间最高价（夹角高点）。
                      </p>
                    </article>
                    <article className="strategy-brief">
                      <header>
                        <span className="strategy-brief-tag fire">爆发</span>
                        <strong>带量突破扳机</strong>
                      </header>
                      <p>
                        收盘突破扳机 + 量 ≥ SMA20×1.5 + MACD 金叉放大 → 多头爆发预警。
                      </p>
                    </article>
                  </div>
                  <p className="pattern-hint-main">← 点击左侧币种查看 15m K 线与形态拐点标注</p>

                  {watchingStates.length > 0 && (
                    <section className="pattern-section">
                      <h3>观察中</h3>
                      <div className="pattern-card-grid">
                        {watchingStates.map((s) => (
                          <button
                            key={s.symbol}
                            type="button"
                            className="pattern-alert-card watch"
                            onClick={() => setSelectedSymbol(s.symbol)}
                          >
                            <div className="pattern-alert-card-head">
                              <span className="coin-avatar sm">{coinInitial(s.symbol)}</span>
                              <strong>${displaySymbol(s.symbol)}</strong>
                              <span className="pattern-alert-badge">{s.status_label}</span>
                            </div>
                            {s.message && <p className="pattern-alert-card-msg">{s.message}</p>}
                            {(s.lh_price ?? 0) > 0 && (
                              <div className="pattern-levels inline">
                                <span>LH {s.lh_price!.toPrecision(4)}</span>
                                {(s.hl ?? 0) > 0 && <span>HL {s.hl!.toPrecision(4)}</span>}
                                {(s.trigger_price ?? 0) > 0 && (
                                  <span>扳机 {s.trigger_price!.toPrecision(4)}</span>
                                )}
                              </div>
                            )}
                          </button>
                        ))}
                      </div>
                    </section>
                  )}

                  <section className="pattern-section">
                    <h3>扳机历史（本轮）</h3>
                    {alerts.length === 0 ? (
                      <p className="pattern-empty">暂无扳机信号，添加币种后自动扫描</p>
                    ) : (
                      <div className="pattern-card-grid">
                        {alerts.map((a) => (
                          <button
                            key={`${a.symbol}-${a.kline_close_time}`}
                            type="button"
                            className="pattern-alert-card fire"
                            onClick={() => setSelectedSymbol(a.symbol)}
                          >
                            <div className="pattern-alert-card-head">
                              <span className="coin-avatar sm">{coinInitial(a.symbol)}</span>
                              <strong>${displaySymbol(a.symbol)}</strong>
                              <span className="pat-fire-tag">多头爆发</span>
                            </div>
                            <p className="pattern-alert-card-msg">{a.message}</p>
                            <div className="pattern-levels inline">
                              <span>HL {a.hl?.toPrecision(4)}</span>
                              <span>突破 {a.trigger_price?.toPrecision(4)}</span>
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </section>
                </div>
              ) : (
                <div className="pattern-tab-panel sandbox-section">
                    <div className="sandbox-head">
                      <h3>沙盒纸面交易 · {sandboxStats?.day ?? "今日"}</h3>
                      <button type="button" className="pattern-random-btn" onClick={reshuffleSandbox} disabled={busy}>
                        重抽今日 12 币
                      </button>
                    </div>
                    <div className="sandbox-manual">
                      <span className="sandbox-manual-label">手动市价进场</span>
                      <input
                        type="text"
                        list="sandbox-sym-suggestions"
                        placeholder={selectedSymbol || "如 BTCUSDT"}
                        value={manualSym}
                        onChange={(e) => setManualSym(e.target.value.toUpperCase())}
                        disabled={busy}
                      />
                      <datalist id="sandbox-sym-suggestions">
                        {[...new Set([...watchlist.map((w) => w.symbol), ...sandboxPool])].map((s) => (
                          <option key={s} value={s} />
                        ))}
                      </datalist>
                      <select
                        value={manualLogic}
                        onChange={(e) => setManualLogic(e.target.value as "S" | "T")}
                        disabled={busy}
                        aria-label="逻辑"
                      >
                        <option value="S">S · 短线猎手</option>
                        <option value="T">T · 长线维加斯</option>
                      </select>
                      <select
                        value={manualSide}
                        onChange={(e) => setManualSide(e.target.value as "LONG" | "SHORT")}
                        disabled={busy}
                        aria-label="方向"
                      >
                        <option value="LONG">做多 LONG</option>
                        <option value="SHORT">做空 SHORT</option>
                      </select>
                      <select
                        value={manualInterval}
                        onChange={(e) => setManualInterval(e.target.value as "15m" | "1h")}
                        disabled={busy}
                        aria-label="执行周期"
                      >
                        {sandboxIntervals.map((iv) => (
                          <option key={iv} value={iv}>
                            {iv}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="pattern-random-btn"
                        onClick={() => void manualSandboxEnter()}
                        disabled={busy}
                      >
                        市价开仓
                      </button>
                    </div>
                    <div className="strategy-brief-grid">
                      <article className="strategy-brief">
                        <header>
                          <span className="strategy-brief-tag">S · 短线猎手</span>
                          <strong>震荡边界偷鸡</strong>
                        </header>
                        <p>
                          RANGE：上轨/LH + 射击之星做空；下轨/HL + 倒锤/锤子做多。止损 = 信号 K 极值 ±0.1%；
                          触及布林中轨或有利 ≥2×ATR 全平。
                        </p>
                      </article>
                      <article className="strategy-brief">
                        <header>
                          <span className="strategy-brief-tag trend">T · 长线维加斯</span>
                          <strong>趋势回踩波段</strong>
                        </header>
                        <p>
                          BULL/BEAR：回踩 EMA12/隧道确认。初始止损距入场不超过
                          2.5×ATR(14)（OI 暴增波动大时自动放宽）。价变 ≥0.75% 保本 → ≥1% 减仓
                          30% → 尾仓自极值回撤 1% 全平。
                        </p>
                      </article>
                      <article className="strategy-brief">
                        <header>
                          <span className="strategy-brief-tag muted">分流 · 风控</span>
                          <strong>Trend_Status</strong>
                        </header>
                        <p>
                          RANGE 只跑 S、趋势只跑 T；保证金 1U，BTC/ETH 100x、山寨 30x；最多同时{" "}
                          {sandboxMaxConcurrent} 币。
                        </p>
                      </article>
                    </div>
                    <p className="pattern-hint-main">
                      日池 {sandboxPool.length} · 周期 {sandboxIntervals.join(" + ")} · 并发≤
                      {sandboxMaxConcurrent} · 余额 {sandboxStats?.balance?.toFixed(2) ?? "—"}U · 胜率{" "}
                      {sandboxStats ? `${(sandboxStats.win_rate * 100).toFixed(0)}%` : "—"} · 今日盈亏{" "}
                      {sandboxStats
                        ? `${sandboxStats.pnl_usd >= 0 ? "+" : ""}${sandboxStats.pnl_usd.toFixed(2)}U`
                        : "—"}
                      {" · "}
                      历史本地近 {SANDBOX_HISTORY_RETAIN_DAYS} 天
                    </p>
                    <div className="sandbox-history-filters">
                      {(
                        [
                          { id: "all" as const, label: "全部" },
                          { id: "st" as const, label: "S/T" },
                          { id: "card" as const, label: "卡片" },
                        ] as const
                      ).map((opt) => (
                        <button
                          key={opt.id}
                          type="button"
                          className={`sandbox-range-btn${sandboxFilter === opt.id ? " active" : ""}`}
                          onClick={() => setSandboxFilter(opt.id)}
                        >
                          {opt.label}
                        </button>
                      ))}
                      <span className="sandbox-filter-sep" aria-hidden>
                        |
                      </span>
                      {SANDBOX_HISTORY_RANGE_OPTIONS.map((opt) => (
                        <button
                          key={opt.id}
                          type="button"
                          className={`sandbox-range-btn${historyRange === opt.id ? " active" : ""}`}
                          onClick={() => setHistoryRange(opt.id)}
                        >
                          {opt.label}
                        </button>
                      ))}
                      <span className="sandbox-range-stats">
                        <span className="sandbox-range-count">
                          {historyRangeStats.trades} 笔
                          {historyRangeStats.trades > 0
                            ? ` · 胜 ${historyRangeStats.wins} / 负 ${historyRangeStats.losses} · 胜率 ${(historyRangeStats.win_rate * 100).toFixed(0)}%`
                            : ""}
                        </span>
                        <span
                          className={`sandbox-range-pnl${
                            historyRangeStats.trades === 0
                              ? ""
                              : historyRangeStats.pnl_usd >= 0
                                ? " pos"
                                : " neg"
                          }`}
                        >
                          盈亏{" "}
                          {historyRangeStats.trades === 0
                            ? "—"
                            : `${historyRangeStats.pnl_usd >= 0 ? "+" : ""}${historyRangeStats.pnl_usd.toFixed(2)}U`}
                        </span>
                      </span>
                    </div>
                    <div className="sandbox-pool">
                      {sandboxPool.length === 0 ? (
                        <span className="pattern-empty">等待扫描生成日池…</span>
                      ) : (
                        sandboxPool.map((sym) => {
                          const entered = enteredSymbols.has(sym.toUpperCase());
                          return (
                            <button
                              key={sym}
                              type="button"
                              className={`sandbox-chip${selectedSymbol === sym ? " active" : ""}${entered ? " entered" : ""}`}
                              onClick={() => setSelectedSymbol(sym)}
                              title={entered ? "沙盒持仓中" : undefined}
                            >
                              ${displaySymbol(sym)}
                              {entered ? <span className="sandbox-chip-mark">持</span> : null}
                            </button>
                          );
                        })
                      )}
                    </div>

                    {filteredCardOrders.length > 0 && (
                      <table className="sandbox-table">
                        <thead>
                          <tr>
                            <th>卡片ID</th>
                            <th>发单时间</th>
                            <th>作者</th>
                            <th>币种</th>
                            <th>状态</th>
                            <th>方向</th>
                            <th>入场</th>
                            <th>止盈</th>
                            <th>止损</th>
                            <th>杠杆</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredCardOrders.map((o) => (
                            <tr
                              key={o.card_id}
                              className="clickable"
                              onClick={() => setSelectedSymbol(o.symbol)}
                            >
                              <td>
                                {o.card_id}
                                {o.source_label || o.channel_name || o.guild_name ? (
                                  <span className="sandbox-pnl-sub">
                                    {[o.guild_name, o.channel_name || o.source_label]
                                      .filter(Boolean)
                                      .join(" · ")}
                                  </span>
                                ) : null}
                              </td>
                              <td>
                                {fmtTs(
                                  o.signal_at || o.created_at || 0
                                )}
                              </td>
                              <td>{o.author_name || "—"}</td>
                              <td>${displaySymbol(o.symbol)}</td>
                              <td>
                                {o.status === "watching"
                                  ? "监听"
                                  : o.status === "near"
                                    ? "近场"
                                    : o.status === "ordered"
                                      ? "挂单"
                                      : o.status === "filled"
                                        ? "已入场"
                                        : o.status}
                              </td>
                              <td>{o.side}</td>
                              <td className="sandbox-tf">
                                {o.entry_type === "market"
                                  ? "市价"
                                  : o.entry_low != null
                                    ? o.entry_high != null && o.entry_high !== o.entry_low
                                      ? `${o.entry_low}-${o.entry_high}`
                                      : String(o.entry_low)
                                    : "—"}
                              </td>
                              <td className="sandbox-tf">
                                {(o.tps || []).length
                                  ? (o.tps || []).join(" · ")
                                  : "—"}
                              </td>
                              <td>{o.sl != null ? fmtMetaPrice(o.sl) : "—"}</td>
                              <td>{o.leverage != null ? `${o.leverage}x` : "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}

                    {filteredPositions.length > 0 && (
                      <table className="sandbox-table">
                        <thead>
                          <tr>
                            <th>币种</th>
                            <th>来源</th>
                            <th>周期</th>
                            <th>模块</th>
                            <th>方向</th>
                            <th>参考周期</th>
                            <th>入场原因</th>
                            <th>入场时间/价</th>
                            <th>止损</th>
                            <th>事件</th>
                            <th>平仓</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredPositions.map((p) => (
                            <tr
                              key={p.id ?? `${p.symbol}-${p.entry_time}-${p.logic}-${p.interval}`}
                              className="clickable"
                              onClick={() => setSelectedSymbol(p.symbol)}
                            >
                              <td>${displaySymbol(p.symbol)}</td>
                              <td>
                                <span
                                  className={`sandbox-src${
                                    p.source === "card" || p.source_label === "卡片"
                                      ? " card"
                                      : (p.source || p.source_label) === "manual" ||
                                          p.source_label === "手动"
                                        ? " manual"
                                        : " auto"
                                  }`}
                                >
                                  {p.source_label ||
                                    (p.source === "manual"
                                      ? "手动"
                                      : p.source === "card"
                                        ? "卡片"
                                        : "自动")}
                                  {p.card_id ? ` · ${p.card_id}` : ""}
                                </span>
                              </td>
                              <td className="sandbox-tf">{p.interval || "15m"}</td>
                              <td>
                                {p.module ||
                                  (p.logic === "S"
                                    ? "短线"
                                    : p.logic === "T"
                                      ? "长线"
                                      : p.logic === "C"
                                        ? "卡片"
                                        : p.logic)}
                              </td>
                              <td>{p.side}</td>
                              <td className="sandbox-tf">
                                {p.ref_intervals_label ||
                                  (p.logic === "T"
                                    ? "15m · 1h · 4h · 1d"
                                    : p.interval || "15m")}
                              </td>
                              <td className="sandbox-events">{p.entry_reason || "—"}</td>
                              <td>
                                {fmtTs(p.entry_time)}
                                <span className="sandbox-pnl-sub">{fmtMetaPrice(p.entry_price)}</span>
                              </td>
                              <td>{fmtMetaPrice(p.sl)}</td>
                              <td className="sandbox-events">{fmtTradeEvents(p.events)}</td>
                              <td
                                className="sandbox-close-cell"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {p.id != null ? (
                                  <div className="sandbox-close-row">
                                    <div className="sandbox-close-presets">
                                      {[25, 50, 75, 100].map((n) => (
                                        <button
                                          key={n}
                                          type="button"
                                          className={`sandbox-close-pct${
                                            (closePctById[p.id!] ?? 100) === n
                                              ? " active"
                                              : ""
                                          }`}
                                          disabled={busy || closingId === p.id}
                                          onClick={() =>
                                            setClosePctById((prev) => ({
                                              ...prev,
                                              [p.id!]: n,
                                            }))
                                          }
                                        >
                                          {n}%
                                        </button>
                                      ))}
                                    </div>
                                    <div className="sandbox-close-actions">
                                      <input
                                        type="number"
                                        min={1}
                                        max={100}
                                        step={1}
                                        className="sandbox-close-input"
                                        value={closePctById[p.id] ?? 100}
                                        disabled={busy || closingId === p.id}
                                        onChange={(e) => {
                                          const v = Math.min(
                                            100,
                                            Math.max(1, Number(e.target.value) || 1),
                                          );
                                          setClosePctById((prev) => ({
                                            ...prev,
                                            [p.id!]: v,
                                          }));
                                        }}
                                      />
                                      <button
                                        type="button"
                                        className="sandbox-close-btn"
                                        disabled={busy || closingId === p.id}
                                        onClick={() =>
                                          void manualSandboxClose(
                                            p.id!,
                                            closePctById[p.id!] ?? 100,
                                          )
                                        }
                                      >
                                        {closingId === p.id ? "…" : "平仓"}
                                      </button>
                                    </div>
                                  </div>
                                ) : (
                                  "—"
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}

                    <table className="sandbox-table">
                      <thead>
                        <tr>
                          <th>日期</th>
                          <th>币种</th>
                          <th>来源</th>
                          <th>周期</th>
                          <th>逻辑</th>
                          <th>方向</th>
                          <th>参考周期</th>
                          <th>入场原因</th>
                          <th>入场时间/价</th>
                          <th>出场时间/价</th>
                          <th>出场逻辑</th>
                          <th>盈亏</th>
                          <th>阶段事件</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredHistory.length === 0 ? (
                          <tr>
                            <td colSpan={13} className="pattern-empty">
                              该时间范围内暂无平仓记录（本地保留近 {SANDBOX_HISTORY_RETAIN_DAYS} 天）
                            </td>
                          </tr>
                        ) : (
                          filteredHistory.map((t) => {
                            const ev =
                              t.stage_events ||
                              fmtTradeEvents(t.events, t.reason);
                            const srcLabel =
                              t.source_label ||
                              (t.source === "card" || t.source === "卡片"
                                ? "卡片"
                                : t.source === "manual" || t.source === "手动"
                                  ? "手动"
                                  : "自动");
                            const exitLabel =
                              t.exit_label ||
                              (t.reason?.includes("|")
                                ? t.reason.split("|")[1]
                                : "") ||
                              "—";
                            return (
                            <tr
                              key={t.key}
                              className="clickable"
                              onClick={() => setSelectedSymbol(t.symbol)}
                            >
                              <td>{t.day.slice(5)}</td>
                              <td>${displaySymbol(t.symbol)}</td>
                              <td>
                                <span
                                  className={`sandbox-src${
                                    srcLabel === "卡片"
                                      ? " card"
                                      : srcLabel === "手动"
                                        ? " manual"
                                        : " auto"
                                  }`}
                                >
                                  {srcLabel}
                                </span>
                              </td>
                              <td className="sandbox-tf">{t.interval || "15m"}</td>
                              <td>{t.logic}</td>
                              <td>{t.side}</td>
                              <td className="sandbox-tf">
                                {t.ref_intervals_label ||
                                  (Array.isArray(t.ref_intervals)
                                    ? t.ref_intervals.join(" · ")
                                    : t.logic === "T"
                                      ? "15m · 1h · 4h · 1d"
                                      : t.interval || "15m")}
                              </td>
                              <td className="sandbox-events">
                                {t.entry_reason || "—"}
                              </td>
                              <td>
                                {t.entry_time ? fmtTs(t.entry_time) : "—"}
                                <span className="sandbox-pnl-sub">{fmtMetaPrice(t.entry_price)}</span>
                              </td>
                              <td>
                                {t.exit_time ? fmtTs(t.exit_time) : "—"}
                                <span className="sandbox-pnl-sub">{fmtMetaPrice(t.exit_price)}</span>
                              </td>
                              <td className="sandbox-events">{exitLabel}</td>
                              <td className={t.pnl_usd >= 0 ? "pos" : "neg"}>
                                {t.pnl_usd >= 0 ? "+" : ""}
                                {t.pnl_usd.toFixed(2)}U
                                <span className="sandbox-pnl-sub">
                                  价{(t.pnl_pct >= 0 ? "+" : "") + t.pnl_pct.toFixed(2)}%
                                  {" · "}
                                  ROE
                                  {(t.roe_pct ?? t.pnl_pct * (t.leverage ?? 30)) >= 0
                                    ? "+"
                                    : ""}
                                  {(
                                    t.roe_pct ?? t.pnl_pct * (t.leverage ?? 30)
                                  ).toFixed(1)}
                                  %
                                  {t.fee_usd != null && Number(t.fee_usd) > 0
                                    ? ` · 费${Number(t.fee_usd).toFixed(4)}U`
                                    : ""}
                                </span>
                              </td>
                              <td className="sandbox-events">{ev}</td>
                            </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                </div>
              )}
        </main>
      </div>

      <PatternToastStack alerts={alerts} scanTs={scanTs} />
      <SandboxToastStack
        alerts={sandboxAlerts}
        scanTs={sandboxScanTs}
        onOpen={setSelectedSymbol}
      />

      {ctxMenu && (
        <div
          className="pattern-ctx-menu"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
          role="menu"
          onMouseDown={(e) => e.stopPropagation()}
        >
          {(() => {
            const item = watchlist.find((w) => w.symbol === ctxMenu.symbol);
            const pinned = Boolean(item?.pinned);
            return (
              <button
                type="button"
                role="menuitem"
                disabled={busy}
                onClick={() => void pinSymbolToTop(ctxMenu.symbol, !pinned)}
              >
                {pinned
                  ? `取消置顶 $${displaySymbol(ctxMenu.symbol)}`
                  : `置顶 $${displaySymbol(ctxMenu.symbol)}（至少 1 天）`}
              </button>
            );
          })()}
        </div>
      )}
    </div>
  );
});

