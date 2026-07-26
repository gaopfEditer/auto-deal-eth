/** 沙盒历史订单：localStorage，最多保留 90 天（支持近三月筛选） */

export const SANDBOX_HISTORY_KEY = "oi_sandbox_trade_history_v1";
export const SANDBOX_HISTORY_RETAIN_DAYS = 90;

export type SandboxHistoryRange = "1d" | "2d" | "7d" | "30d" | "90d";

export const SANDBOX_HISTORY_RANGE_OPTIONS: Array<{
  id: SandboxHistoryRange;
  label: string;
  days: number;
}> = [
  { id: "1d", label: "今日", days: 1 },
  { id: "2d", label: "近两天", days: 2 },
  { id: "7d", label: "近一周", days: 7 },
  { id: "30d", label: "近一月", days: 30 },
  { id: "90d", label: "近三月", days: 90 },
];

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
  exit_code?: string;
  exit_label?: string;
  fee_usd?: number;
  fee_pct?: number;
  interval?: string;
  ref_intervals?: string[];
  ref_intervals_label?: string;
  /** 合并后的阶段事件文案（; 分隔） */
  stage_events?: string;
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
  exit_code?: string;
  exit_label?: string;
  fee_usd?: number;
  fee_pct?: number;
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

/** 同笔仓位分组键：币种+方向+逻辑+入场时间 */
export function positionGroupKey(t: {
  symbol: string;
  side: string;
  logic: string;
  entry_time?: number;
}): string {
  return [
    String(t.symbol).toUpperCase(),
    t.side,
    t.logic,
    t.entry_time ?? 0,
  ].join("|");
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
  is_partial?: number;
}): string {
  // 同仓多段（减仓+全平）共用 group key，便于合并
  if (!t.is_partial) {
    return `pos:${positionGroupKey(t)}`;
  }
  if (t.id != null && t.id !== "") return `id:${t.id}`;
  return [
    "partial",
    positionGroupKey(t),
    t.exit_time ?? 0,
    Number(t.exit_price).toFixed(8),
  ].join("|");
}

function fmtPx(n: unknown): string {
  const v = Number(n);
  if (!Number.isFinite(v)) return "";
  if (Math.abs(v) >= 1000) return v.toFixed(2);
  if (Math.abs(v) >= 1) return v.toFixed(4);
  return v.toPrecision(4);
}

/** 阶段事件合并为一条，用 ; 分隔 */
export function formatStageEvents(
  events?: Array<Record<string, unknown>>,
  fallbackReason?: string,
): string {
  if (!events?.length) {
    return fallbackReason?.trim() || "—";
  }
  const parts: string[] = [];
  for (const e of events) {
    const typ = String(e.type || "");
    if (!typ || typ === "sync") continue;
    const label =
      typ === "entry"
        ? "入"
        : typ === "exit"
          ? "出"
          : typ === "partial"
            ? "减"
            : typ === "trail"
              ? "移"
              : typ;
    const exitLabel = e.exit_label ? String(e.exit_label) : "";
    const msg = String(e.message || e.entry_reason || e.reason || exitLabel || "");
    const px = e.price != null ? `@${fmtPx(e.price)}` : "";
    const sl = e.sl != null ? ` SL${fmtPx(e.sl)}` : "";
    const bit = exitLabel && typ === "exit"
      ? `${label}${px}${sl} ${exitLabel}`
      : msg
        ? `${label}${px}${sl} ${msg}`
        : `${label}${px}${sl}`;
    const cleaned = bit.replace(/\s+/g, " ").trim();
    if (cleaned && !parts.includes(cleaned)) parts.push(cleaned);
  }
  if (!parts.length) return fallbackReason?.trim() || "—";
  return parts.join("; ");
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
  let exitCode = String(raw.exit_code || "");
  let exitLabel = String(raw.exit_label || "");
  if (!exitCode && raw.reason && String(raw.reason).includes("|")) {
    const parts = String(raw.reason).split("|", 2);
    exitCode = parts[0];
    exitLabel = exitLabel || parts[1] || "";
  }
  if (!exitCode && Array.isArray(events)) {
    const ex = [...events].reverse().find((e) => e?.type === "exit");
    if (ex) {
      exitCode = String(ex.exit_code || ex.reason || "");
      exitLabel = exitLabel || String(ex.exit_label || "");
    }
  }
  const stage = formatStageEvents(
    Array.isArray(events) ? events : undefined,
    String(raw.reason || ""),
  );
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
    exit_code: exitCode,
    exit_label: exitLabel,
    fee_usd: raw.fee_usd != null ? Number(raw.fee_usd) : undefined,
    fee_pct: raw.fee_pct != null ? Number(raw.fee_pct) : undefined,
    interval: String(raw.interval || "15m"),
    ref_intervals: refs,
    ref_intervals_label: raw.ref_intervals_label || refs.join(" · "),
    stage_events: stage,
  };
}

/** 把同仓减仓行 + 全平行合并为一条 */
export function mergeLinkedTrades(trades: SandboxHistoryTrade[]): SandboxHistoryTrade[] {
  const groups = new Map<string, SandboxHistoryTrade[]>();
  for (const t of trades) {
    const gk = positionGroupKey(t);
    const list = groups.get(gk) || [];
    list.push(t);
    groups.set(gk, list);
  }
  const out: SandboxHistoryTrade[] = [];
  for (const [, rows] of groups) {
    if (rows.length === 1) {
      const only = rows[0];
      out.push({
        ...only,
        stage_events: only.stage_events || formatStageEvents(only.events, only.reason),
      });
      continue;
    }
    rows.sort((a, b) => (a.exit_time || 0) - (b.exit_time || 0));
    const finals = rows.filter((r) => !r.is_partial);
    const base = finals.length ? finals[finals.length - 1] : rows[rows.length - 1];
    const eventMap = new Map<string, Record<string, unknown>>();
    for (const r of rows) {
      for (const e of r.events || []) {
        const k = `${e.type}|${e.time}|${e.price}|${e.message || e.reason || ""}`;
        if (!eventMap.has(k)) eventMap.set(k, e);
      }
    }
    const events = [...eventMap.values()].sort(
      (a, b) => Number(a.time || 0) - Number(b.time || 0),
    );
    const pnl = rows.reduce((s, r) => s + (Number(r.pnl_usd) || 0), 0);
    const fee = rows.reduce((s, r) => s + (Number(r.fee_usd) || 0), 0);
    out.push({
      ...base,
      key: `pos:${positionGroupKey(base)}`,
      pnl_usd: pnl,
      fee_usd: fee || base.fee_usd,
      is_partial: 0,
      events,
      exit_code: base.exit_code || rows.map((r) => r.exit_code).find(Boolean),
      exit_label: base.exit_label || rows.map((r) => r.exit_label).find(Boolean),
      stage_events: formatStageEvents(events, base.reason),
      saved_at: Math.min(...rows.map((r) => r.saved_at || Date.now())),
    });
  }
  return out.sort((a, b) => (b.exit_time || b.saved_at) - (a.exit_time || a.saved_at));
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

export function filterHistoryByRange(
  trades: SandboxHistoryTrade[],
  range: SandboxHistoryRange,
): SandboxHistoryTrade[] {
  const opt = SANDBOX_HISTORY_RANGE_OPTIONS.find((o) => o.id === range);
  const days = opt?.days ?? 1;
  const cutoff = cutoffDayKey(days);
  const cutoffMs = (() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - (days - 1));
    return d.getTime();
  })();
  return trades.filter((t) => {
    if (t.day && t.day >= cutoff) return true;
    if (t.exit_time > 0) return t.exit_time * 1000 >= cutoffMs;
    return t.saved_at >= cutoffMs;
  });
}

export type SandboxHistoryRangeStats = {
  trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  pnl_usd: number;
  fee_usd: number;
};

/** 当前筛选维度下的笔数 / 胜率 / 盈亏汇总 */
export function summarizeHistoryRange(
  trades: SandboxHistoryTrade[],
): SandboxHistoryRangeStats {
  let wins = 0;
  let losses = 0;
  let pnl = 0;
  let fee = 0;
  for (const t of trades) {
    const p = Number(t.pnl_usd) || 0;
    pnl += p;
    fee += Number(t.fee_usd) || 0;
    if (p > 0) wins += 1;
    else if (p < 0) losses += 1;
  }
  const n = trades.length;
  return {
    trades: n,
    wins,
    losses,
    win_rate: n > 0 ? wins / n : 0,
    pnl_usd: pnl,
    fee_usd: fee,
  };
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
    return mergeLinkedTrades(pruneHistory(trades));
  } catch {
    return [];
  }
}

export function saveSandboxHistory(trades: SandboxHistoryTrade[]): SandboxHistoryTrade[] {
  const next = mergeLinkedTrades(pruneHistory(trades));
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
    if (prev && n.is_partial && !prev.is_partial) {
      // 旧减仓行撞上已合并全平：并入事件与盈亏
      const events = [...(prev.events || []), ...(n.events || [])];
      map.set(prev.key, {
        ...prev,
        pnl_usd: (prev.pnl_usd || 0) + (n.pnl_usd || 0),
        events,
        stage_events: formatStageEvents(events, prev.reason),
      });
      continue;
    }
    map.set(n.key, prev ? { ...n, saved_at: prev.saved_at, key: prev.key } : n);
  }
  return saveSandboxHistory([...map.values()]);
}
