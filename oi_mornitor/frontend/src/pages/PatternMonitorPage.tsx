import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type { PatternAlert, PatternState, PatternWatchItem } from "../types";
import { coinInitial, displaySymbol } from "../utils/symbol";
import { MercuHeader } from "../components/MercuHeader";
import { PatternChartPanel } from "../components/PatternChartPanel";
import { PatternToastStack } from "../components/PatternToastStack";
import { SandboxToastStack } from "../components/SandboxToastStack";
import { useRadarSSE } from "../hooks/useRadarSSE";
import { useSandboxTradeHistory } from "../hooks/useSandboxTradeHistory";
import { fmtMetaPrice, fmtTs } from "../utils/format";
import { SANDBOX_HISTORY_RETAIN_DAYS } from "../utils/sandboxHistory";

function fmtTradeEvents(events?: Array<Record<string, unknown>>): string {
  if (!events?.length) return "—";
  return events
    .filter((e) => e.type && e.type !== "sync")
    .slice(-4)
    .map((e) => {
      const t = e.type === "entry" ? "入" : e.type === "exit" ? "出" : e.type === "partial" ? "减" : "移";
      const px = e.price != null ? fmtMetaPrice(Number(e.price)) : "";
      const sl = e.sl != null ? ` SL${fmtMetaPrice(Number(e.sl))}` : "";
      return `${t}@${px}${sl}`;
    })
    .join(" → ");
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
  const sandboxHistory = useSandboxTradeHistory({
    recentTrades: sandboxStats?.recent_trades,
    day: sandboxStats?.day,
    exitAlerts: sandboxExitAlerts,
    scanTs: sandboxScanTs,
  });
  const watchingStates = useMemo(
    () =>
      states.filter(
        (s) => s.status === "STAGE_1_LH_DETECTED" || s.status === "WAITING_FOR_HL",
      ),
    [states],
  );
  const sandboxOn = pattern?.sandbox_enabled !== false;
  const sandboxMaxConcurrent = pattern?.sandbox_max_concurrent ?? 10;
  const enteredSymbols = useMemo(
    () => new Set(sandboxPositions.map((p) => p.symbol.toUpperCase())),
    [sandboxPositions],
  );

  const [manualSym, setManualSym] = useState("");
  const [manualLogic, setManualLogic] = useState<"S" | "T">("S");
  const [manualSide, setManualSide] = useState<"LONG" | "SHORT">("LONG");

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
    async (args?: { symbol?: string; logic?: "S" | "T"; side?: "LONG" | "SHORT" }) => {
      const sym = (args?.symbol || manualSym || selectedSymbol || "").trim().toUpperCase();
      const logic = args?.logic || manualLogic;
      const side = args?.side || manualSide;
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
          body: JSON.stringify({ symbol: sym, logic, side }),
        });
        const data = await res.json();
        if (!data.ok) setErr(data.error || "市价开仓失败");
        else {
          setMainTab("sandbox");
          setSelectedSymbol(sym);
        }
      } catch {
        setErr("网络错误");
      } finally {
        setBusy(false);
      }
    },
    [manualSym, selectedSymbol, manualLogic, manualSide],
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
            已监听 {watchlist.length} / 30（亮色=已置顶 ≥1 天）
          </p>

          <ul className="pattern-watchlist">
            {watchlist.length === 0 ? (
              <li className="pattern-empty">等待雷达扫描后按合约流入 / OI 爆发自动挑选…</li>
            ) : (
              watchlist.map((w) => {
                const st = states.find((s) => s.symbol === w.symbol);
                const cls = STATUS_CLASS[st?.status ?? "SEARCHING_TOP"] ?? "pat-search";
                const active = selectedSymbol === w.symbol;
                const pinned = Boolean(w.pinned);
                const entered = enteredSymbols.has(w.symbol.toUpperCase());
                const pinHours =
                  pinned && (w.pin_remaining_sec ?? 0) > 0
                    ? Math.max(1, Math.ceil((w.pin_remaining_sec ?? 0) / 3600))
                    : 0;
                return (
                  <li
                    key={w.symbol}
                    className={`pattern-watch-item ${cls}${active ? " active" : ""}${pinned ? " pinned" : ""}${entered ? " entered" : ""}`}
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
                          BULL/BEAR：回踩 EMA12/隧道确认。价变 ≥0.75% 保本 → ≥1% 减仓 30% →
                          尾仓自极值回撤 1% 全平。
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
                      日池 {sandboxPool.length} · 并发≤{sandboxMaxConcurrent} ·
                      余额 {sandboxStats?.balance?.toFixed(2) ?? "—"}U · 胜率{" "}
                      {sandboxStats ? `${(sandboxStats.win_rate * 100).toFixed(0)}%` : "—"} · 今日盈亏{" "}
                      {sandboxStats
                        ? `${sandboxStats.pnl_usd >= 0 ? "+" : ""}${sandboxStats.pnl_usd.toFixed(2)}U`
                        : "—"}
                      {" · "}
                      历史本地近 {SANDBOX_HISTORY_RETAIN_DAYS} 天（{sandboxHistory.length} 笔）
                    </p>
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

                    {sandboxPositions.length > 0 && (
                      <table className="sandbox-table">
                        <thead>
                          <tr>
                            <th>币种</th>
                            <th>来源</th>
                            <th>模块</th>
                            <th>方向</th>
                            <th>参考周期</th>
                            <th>入场原因</th>
                            <th>入场时间/价</th>
                            <th>止损</th>
                            <th>事件</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sandboxPositions.map((p) => (
                            <tr
                              key={p.id ?? `${p.symbol}-${p.entry_time}-${p.logic}`}
                              className="clickable"
                              onClick={() => setSelectedSymbol(p.symbol)}
                            >
                              <td>${displaySymbol(p.symbol)}</td>
                              <td>
                                <span
                                  className={`sandbox-src${
                                    (p.source || p.source_label) === "manual" ||
                                    p.source_label === "手动"
                                      ? " manual"
                                      : " auto"
                                  }`}
                                >
                                  {p.source_label ||
                                    (p.source === "manual" ? "手动" : "自动")}
                                </span>
                              </td>
                              <td>
                                {p.module || (p.logic === "S" ? "短线" : p.logic === "T" ? "长线" : p.logic)}
                              </td>
                              <td>{p.side}</td>
                              <td className="sandbox-tf">
                                {p.ref_intervals_label ||
                                  (p.logic === "T" ? "15m · 1h · 4h · 1d" : "15m")}
                              </td>
                              <td className="sandbox-events">{p.entry_reason || "—"}</td>
                              <td>
                                {fmtTs(p.entry_time)}
                                <span className="sandbox-pnl-sub">{fmtMetaPrice(p.entry_price)}</span>
                              </td>
                              <td>{fmtMetaPrice(p.sl)}</td>
                              <td className="sandbox-events">{fmtTradeEvents(p.events)}</td>
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
                          <th>逻辑</th>
                          <th>方向</th>
                          <th>参考周期</th>
                          <th>入场原因</th>
                          <th>入场时间/价</th>
                          <th>出场时间/价</th>
                          <th>盈亏</th>
                          <th>阶段事件</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sandboxHistory.length === 0 ? (
                          <tr>
                            <td colSpan={11} className="pattern-empty">
                              暂无平仓记录（本地保留近 {SANDBOX_HISTORY_RETAIN_DAYS} 天）
                            </td>
                          </tr>
                        ) : (
                          sandboxHistory.map((t) => {
                            const ev = fmtTradeEvents(t.events);
                            const srcLabel =
                              t.source_label ||
                              (t.source === "manual" || t.source === "手动" ? "手动" : "自动");
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
                                    srcLabel === "手动" ? " manual" : " auto"
                                  }`}
                                >
                                  {srcLabel}
                                </span>
                              </td>
                              <td>{t.logic}</td>
                              <td>{t.side}</td>
                              <td className="sandbox-tf">
                                {t.ref_intervals_label ||
                                  (Array.isArray(t.ref_intervals)
                                    ? t.ref_intervals.join(" · ")
                                    : t.logic === "T"
                                      ? "15m · 1h · 4h · 1d"
                                      : "15m")}
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
                                </span>
                              </td>
                              <td className="sandbox-events">
                                {ev !== "—" ? ev : t.reason}
                              </td>
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

