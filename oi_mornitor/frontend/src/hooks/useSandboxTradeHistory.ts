import { useEffect, useMemo, useState } from "react";
import type { PatternAlert } from "../types";
import {
  loadSandboxHistory,
  mergeSandboxHistory,
  type SandboxHistoryTrade,
  type SandboxTradeInput,
} from "../utils/sandboxHistory";

function alertToTrade(a: PatternAlert): SandboxTradeInput | null {
  if (a.type !== "exit") return null;
  const entry = a.entry_price;
  const exit = a.exit_price ?? a.price;
  if (entry == null || exit == null || a.pnl_usd == null) return null;
  return {
    symbol: a.symbol,
    side: a.side || "",
    logic: a.logic || "",
    entry_price: entry,
    exit_price: exit,
    entry_time: a.entry_time,
    exit_time: a.kline_close_time || a.exit_time,
    leverage: a.leverage,
    pnl_usd: a.pnl_usd,
    pnl_pct: a.pnl_pct ?? 0,
    roe_pct: a.roe_pct,
    reason: a.message || "",
  };
}

/** 把服务端 recent_trades + 平仓 toast 合并进 localStorage（最多 3 天） */
export function useSandboxTradeHistory(opts: {
  recentTrades?: SandboxTradeInput[] | null;
  day?: string;
  exitAlerts?: PatternAlert[];
  scanTs?: number;
}): SandboxHistoryTrade[] {
  const [trades, setTrades] = useState<SandboxHistoryTrade[]>(() =>
    typeof window !== "undefined" ? loadSandboxHistory() : [],
  );

  const serverSig = useMemo(() => {
    const list = opts.recentTrades ?? [];
    return list
      .map(
        (t) =>
          `${t.symbol}:${t.entry_time ?? 0}:${t.exit_time ?? 0}:${t.pnl_usd}:${t.exit_price}`,
      )
      .join("|");
  }, [opts.recentTrades]);

  const alertSig = useMemo(() => {
    return (opts.exitAlerts ?? [])
      .filter((a) => a.type === "exit")
      .map(
        (a) =>
          `${a.symbol}:${a.kline_close_time}:${a.pnl_usd ?? ""}:${a.entry_price ?? ""}:${a.exit_price ?? a.price ?? ""}`,
      )
      .join("|");
  }, [opts.exitAlerts]);

  useEffect(() => {
    const incoming: SandboxTradeInput[] = [...(opts.recentTrades ?? [])];
    for (const a of opts.exitAlerts ?? []) {
      const t = alertToTrade(a);
      if (t) incoming.push(t);
    }
    if (!incoming.length) {
      setTrades(loadSandboxHistory());
      return;
    }
    setTrades(mergeSandboxHistory(incoming, opts.day));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 用 fingerprint 驱动合并
  }, [serverSig, alertSig, opts.day, opts.scanTs]);

  return trades;
}
