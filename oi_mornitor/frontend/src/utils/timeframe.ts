import type {
  FlowWindowSnapshot,
  OiByTf,
  OiTimeframe,
  PriceByTf,
  RankDomain,
  RankMetricSnapshot,
  TickerRow,
} from "../types";

export const TIMEFRAMES: OiTimeframe[] = ["15m", "30m", "1h", "4h", "1d"];

const EMPTY_FLOW = { net_usd: 0, volume_usd: 0 };
const EMPTY_PRICE = { pct: 0 };
const EMPTY_RANK: RankMetricSnapshot = {
  magnitude_usd: 0,
  change_rate: 0,
  z_score: 0,
  intensity_score: 0,
};

export function getOiWindow(row: TickerRow, tf: OiTimeframe): { delta_usd: number; pct: number } {
  const fromMap = row.oi_by_tf?.[tf];
  const raw = fromMap
    ? fromMap
    : tf === "15m"
      ? { delta_usd: row.delta_15m_usd ?? 0, pct: row.pct_15m ?? 0 }
      : { delta_usd: row.delta_5m_usd ?? 0, pct: row.pct_5m ?? 0 };

  // 前端兜底：屏蔽历史脏点导致的荒谬 OI 差分（与后端 OI_DELTA_MAX_PCT 对齐）
  const maxPct = 150;
  if (!Number.isFinite(raw.pct) || Math.abs(raw.pct) > maxPct) {
    return { delta_usd: 0, pct: 0 };
  }
  const oiUsd = row.current_oi_usd ?? 0;
  if (oiUsd > 0 && Math.abs(raw.delta_usd) > oiUsd * (1 + maxPct / 100)) {
    return { delta_usd: 0, pct: 0 };
  }
  return raw;
}

export function getPriceWindow(row: TickerRow, tf: OiTimeframe): PriceWindowSnapshot {
  const fromMap = row.price_by_tf?.[tf];
  if (fromMap) return fromMap;
  if (tf === "15m" || tf === "30m") {
    return { pct: row.pct_price_5m ?? 0 };
  }
  return EMPTY_PRICE;
}

export function getFlowWindow(row: TickerRow, tf: OiTimeframe): FlowWindowSnapshot {
  return row.flow_by_tf?.[tf] ?? EMPTY_FLOW;
}

export function getSpotFlowWindow(row: TickerRow, tf: OiTimeframe): FlowWindowSnapshot {
  return row.spot_flow_by_tf?.[tf] ?? EMPTY_FLOW;
}

export function getRankMetric(
  row: TickerRow,
  tf: OiTimeframe,
  domain: RankDomain,
): RankMetricSnapshot {
  return row.rank_by_tf?.[tf]?.[domain] ?? EMPTY_RANK;
}

/** 强度榜：取 OI % 与价格 % 中绝对值更大者（保留正负号）。 */
export function strengthPct(row: TickerRow, tf: OiTimeframe): number {
  const oiPct = getOiWindow(row, tf).pct;
  const pricePct = getPriceWindow(row, tf).pct;
  return Math.abs(oiPct) >= Math.abs(pricePct) ? oiPct : pricePct;
}

export function strengthMagnitude(row: TickerRow, tf: OiTimeframe): number {
  return Math.abs(strengthPct(row, tf));
}

export function matrixTopLabel(tf: OiTimeframe, top = 7): string {
  return `${tf} OI · Top ${top}`;
}

export function tfSubtitle(tf: OiTimeframe, suffix: string): string {
  return `${tf} ${suffix}`;
}

export function emptyOiByTf(): OiByTf {
  return {
    "15m": { delta_usd: 0, pct: 0 },
    "30m": { delta_usd: 0, pct: 0 },
    "1h": { delta_usd: 0, pct: 0 },
    "4h": { delta_usd: 0, pct: 0 },
    "1d": { delta_usd: 0, pct: 0 },
  };
}
