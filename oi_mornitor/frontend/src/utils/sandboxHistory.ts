/** 沙盒历史订单：localStorage，最多保留 3 天 */

export const SANDBOX_HISTORY_KEY = "oi_sandbox_trade_history_v1";
export const SANDBOX_HISTORY_RETAIN_DAYS = 3;

export interface SandboxHistoryTrade {
  key: string;
  symbol: string;
  side: string;
  logic: string;
  entry_price: number;
  exit_price: number;
  entry_time: number;
  exit_time: number;
  leverage?: number;
  pnl_usd: number;
  pnl_pct: number;
  roe_pct?: number;
  reason: string;
  day: string;
  saved_at: number;
  events?: Array<Record<string, unknown>>;
  is_partial?: number;
  entry_reason?: string;
  source?: string;
  source_label?: string;
  interval?: string;
  ref_intervals?: string[];
  ref_intervals_label?: string;
}

export type SandboxTradeInput = {
  id?: number | string;
  symbol: string;
  side: string;
  logic: string;
  entry_price: number;
  exit_price: number;
  entry_time?: number;
  exit_time?: number;
  leverage?: number;
  pnl_usd: number;
  pnl_pct: number;
  roe_pct?: number;
  reason?: string;
  day?: string;
  events?: Array<Record<string, unknown>>;
  events_json?: string;
  is_partial?: number;
  entry_reason?: string;
  source?: string;
  source_label?: string;
  interval?: string;
  ref_intervals?: string[] | string;
  ref_intervals_label?: string;
};

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

export function localDayKey(tsSec?: number): string {
  const d = tsSec != null && tsSec > 0 ? new Date(tsSec * 1000) : new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function cutoffDayKey(retainDays = SANDBOX_HISTORY_RETAIN_DAYS): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - (retainDays - 1));
  return localDayKey(Math.floor(d.getTime() / 1000));
}

export function tradeKey(t: {
  symbol: string;
  side: string;
  logic: string;
  entry_time?: number;
  exit_time?: number;
  entry_price: number;
  exit_price: number;
  id?: number | string;
}): string {
  if (t.id != null && t.id !== "") return `id:${t.id}`;
  return [
    String(t.symbol).toUpperCase(),
    t.side,
    t.logic,
    t.entry_time ?? 0,
    t.exit_time ?? 0,
    Number(t.entry_price).toFixed(8),
    Number(t.exit_price).toFixed(8),
  ].join("|");
}

export function normalizeTrade(
  raw: SandboxTradeInput,
  fallbackDay?: string,
): SandboxHistoryTrade | null {
  const symbol = String(raw.symbol || "").toUpperCase();
  if (!symbol || raw.entry_price == null || raw.exit_price == null) return null;
  const entry_time = Number(raw.entry_time || 0);
  const exit_time = Number(raw.exit_time || 0);
  const day =
    raw.day ||
    (exit_time > 0 ? localDayKey(exit_time) : fallbackDay) ||
    localDayKey();
  let events = raw.events;
  if (!events && raw.events_json) {
    try {
      events = JSON.parse(raw.events_json) as Array<Record<string, unknown>>;
    } catch {
      events = [];
    }
  }
  let refs: string[] = [];
  if (Array.isArray(raw.ref_intervals)) {
    refs = raw.ref_intervals.map(String);
  } else if (typeof raw.ref_intervals === "string" && raw.ref_intervals.trim()) {
    refs = raw.ref_intervals.split(/[,·|]/).map((x) => x.trim()).filter(Boolean);
  }
  if (!refs.length) {
    const logic = String(raw.logic || "S");
    refs = logic === "T" ? ["15m", "1h", "4h", "1d"] : ["15m"];
  }
  let entryReason = String(raw.entry_reason || "");
  if (!entryReason && Array.isArray(events)) {
    const ent = events.find((e) => e?.type === "entry");
    if (ent) {
      entryReason = String(ent.entry_reason || ent.message || "");
    }
  }
  let source = String(raw.source || "").toLowerCase();
  let sourceLabel = String(raw.source_label || "");
  if (!source && Array.isArray(events)) {
    const ent = events.find((e) => e?.type === "entry");
    if (ent) {
      source = String(ent.source || "").toLowerCase();
      if (!sourceLabel) sourceLabel = String(ent.source_label || "");
    }
  }
  if (!source) {
    source = entryReason.startsWith("手动") ? "manual" : "auto";
  }
  if (!sourceLabel) {
    sourceLabel = source === "manual" || source === "手动" ? "手动" : "自动";
  }
  return {
    key: tradeKey({ ...raw, symbol, entry_time, exit_time }),
    symbol,
    side: String(raw.side || ""),
    logic: String(raw.logic || ""),
    entry_price: Number(raw.entry_price),
    exit_price: Number(raw.exit_price),
    entry_time,
    exit_time,
    leverage: raw.leverage != null ? Number(raw.leverage) : undefined,
    pnl_usd: Number(raw.pnl_usd) || 0,
    pnl_pct: Number(raw.pnl_pct) || 0,
    roe_pct: raw.roe_pct != null ? Number(raw.roe_pct) : undefined,
    reason: String(raw.reason || ""),
    day,
    saved_at: Date.now(),
    events: Array.isArray(events) ? events : undefined,
    is_partial: raw.is_partial,
    entry_reason: entryReason,
    source,
    source_label: sourceLabel,
    interval: String(raw.interval || "15m"),
    ref_intervals: refs,
    ref_intervals_label: raw.ref_intervals_label || refs.join(" · "),
  };
}

export function pruneHistory(
  trades: SandboxHistoryTrade[],
  retainDays = SANDBOX_HISTORY_RETAIN_DAYS,
): SandboxHistoryTrade[] {
  const cutoff = cutoffDayKey(retainDays);
  const cutoffMs = Date.now() - retainDays * 86400000;
  return trades
    .filter((t) => {
      if (t.day && t.day >= cutoff) return true;
      if (t.exit_time > 0) return t.exit_time * 1000 >= cutoffMs;
      return t.saved_at >= cutoffMs;
    })
    .sort((a, b) => (b.exit_time || b.saved_at) - (a.exit_time || a.saved_at));
}

export function loadSandboxHistory(): SandboxHistoryTrade[] {
  try {
    const raw = localStorage.getItem(SANDBOX_HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const trades = parsed
      .map((row) => {
        if (!row || typeof row !== "object") return null;
        const r = row as SandboxTradeInput & { key?: string; saved_at?: number };
        const n = normalizeTrade(r, r.day);
        if (!n) return null;
        if (r.key) n.key = String(r.key);
        if (r.saved_at) n.saved_at = Number(r.saved_at);
        return n;
      })
      .filter((t): t is SandboxHistoryTrade => t != null);
    return pruneHistory(trades);
  } catch {
    return [];
  }
}

export function saveSandboxHistory(trades: SandboxHistoryTrade[]): SandboxHistoryTrade[] {
  const next = pruneHistory(trades);
  try {
    localStorage.setItem(SANDBOX_HISTORY_KEY, JSON.stringify(next));
  } catch {
    // quota / private mode
  }
  return next;
}

/** 合并服务端/告警成交进本地历史并落盘 */
export function mergeSandboxHistory(
  incoming: SandboxTradeInput[],
  fallbackDay?: string,
): SandboxHistoryTrade[] {
  const map = new Map<string, SandboxHistoryTrade>();
  for (const t of loadSandboxHistory()) map.set(t.key, t);
  for (const raw of incoming) {
    const n = normalizeTrade(raw, fallbackDay);
    if (!n) continue;
    const prev = map.get(n.key);
    map.set(n.key, prev ? { ...n, saved_at: prev.saved_at } : n);
  }
  return saveSandboxHistory([...map.values()]);
}
