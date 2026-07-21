import type { TickerRow } from "../types";

export type OiAlertWindow = "5m" | "15m";

export interface OiAlertItem {
  id: string;
  row: TickerRow;
  window: OiAlertWindow;
  deltaUsd: number;
  pct: number;
  isPump: boolean;
  isSuppressed: boolean;
}

/** 与后端 OI_DELTA_MAX_PCT 对齐：超过视为脏数据，不进异动流 */
const OI_DELTA_MAX_PCT = 150;

function isTriggered(
  deltaUsd: number,
  pct: number,
  usdLimit: number,
  pctLimit: number,
): boolean {
  return Math.abs(deltaUsd) >= usdLimit || Math.abs(pct) >= pctLimit;
}

function isPlausibleOiDelta(
  deltaUsd: number,
  pct: number,
  currentOiUsd: number,
): boolean {
  if (!Number.isFinite(deltaUsd) || !Number.isFinite(pct)) return false;
  if (Math.abs(pct) > OI_DELTA_MAX_PCT) return false;
  // Δ 不应远超当前持仓量级（脏基线常见表现）
  if (currentOiUsd > 0 && Math.abs(deltaUsd) > currentOiUsd * (1 + OI_DELTA_MAX_PCT / 100)) {
    return false;
  }
  return true;
}

function windowRank(window: OiAlertWindow): number {
  return window === "15m" ? 2 : 1;
}

/** 从全量扫描行派生 5m / 15m OI 暴涨暴跌异动（每轮 SSE 实时，不依赖 is_hot 轮询门控）。 */
export function deriveOiAlerts(
  rows: TickerRow[],
  thresholds: { oi_usd_limit: number; oi_pct_limit: number },
  maxItems = 40,
): OiAlertItem[] {
  const { oi_usd_limit: usdLimit, oi_pct_limit: pctLimit } = thresholds;
  const items: OiAlertItem[] = [];

  for (const row of rows) {
    if (row.status === "warming") continue;

    const windows: Array<{ window: OiAlertWindow; deltaUsd: number; pct: number }> = [
      { window: "5m", deltaUsd: row.delta_5m_usd, pct: row.pct_5m },
      { window: "15m", deltaUsd: row.delta_15m_usd, pct: row.pct_15m },
    ];

    for (const w of windows) {
      if (!isTriggered(w.deltaUsd, w.pct, usdLimit, pctLimit)) continue;
      if (!isPlausibleOiDelta(w.deltaUsd, w.pct, row.current_oi_usd ?? 0)) continue;

      const rawWins = row.raw_triggered_windows ?? [];
      const trigWins = row.triggered_windows ?? [];
      const inRaw = rawWins.includes(w.window);
      const inTrig = trigWins.includes(w.window);
      const isSuppressed = inRaw && !inTrig;

      items.push({
        id: `${row.symbol}-${w.window}`,
        row,
        window: w.window,
        deltaUsd: w.deltaUsd,
        pct: w.pct,
        isPump: w.deltaUsd > 0,
        isSuppressed,
      });
    }
  }

  items.sort((a, b) => {
    const mag = Math.abs(b.pct) - Math.abs(a.pct);
    if (mag !== 0) return mag;
    const win = windowRank(b.window) - windowRank(a.window);
    if (win !== 0) return win;
    return (a.row.global_intensity_rank ?? 999) - (b.row.global_intensity_rank ?? 999);
  });

  return items.slice(0, maxItems);
}
