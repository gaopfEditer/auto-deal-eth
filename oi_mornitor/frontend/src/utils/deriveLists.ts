import type { CapitalBiasItem, MatrixRow, OiTimeframe, RankDomain, TickerRow } from "../types";
import { getFlowWindow, getOiWindow, getRankMetric, getSpotFlowWindow } from "./timeframe";
import { fmtNum } from "./format";

const TOP = 7;

function toMatrixRow(
  row: TickerRow,
  rank: number,
  score: number,
  barScore: number,
  category: string,
  tf: OiTimeframe,
): MatrixRow {
  const win = getOiWindow(row, tf);
  return {
    symbol: row.symbol,
    category,
    matrix_rank: rank,
    matrix_score: score,
    matrix_bar: barScore,
    last_price: row.last_price,
    price_change_pct_24h: row.price_change_pct_24h ?? 0,
    quote_volume: row.quote_volume,
    volume_rank: row.volume_rank,
    current_oi_usd: row.current_oi_usd,
    delta_5m_usd: win.delta_usd,
    pct_5m: win.pct,
    delta_15m_usd: win.delta_usd,
    pct_15m: win.pct,
    global_intensity_rank: row.global_intensity_rank,
    global_volume_rank: row.global_volume_rank,
  };
}

function eligible(rows: TickerRow[]): TickerRow[] {
  return rows.filter((r) => r.status !== "warming");
}

function pctFromRate(rate: number): number {
  return rate * 100;
}

/** 负向榜（流出/跌幅）显示负数；正向榜显示正数 */
function displayScore(
  m: ReturnType<typeof getRankMetric>,
  positive: boolean,
  unit: "pct" | "mk",
): number {
  if (unit === "pct") return pctFromRate(m.change_rate);
  const abs = Math.abs(m.magnitude_usd);
  return positive ? abs : -abs;
}

function absRankScore(
  m: ReturnType<typeof getRankMetric>,
  unit: "pct" | "mk",
): number {
  return unit === "pct" ? Math.abs(pctFromRate(m.change_rate)) : Math.abs(m.magnitude_usd);
}

function deriveMagnitudeList(
  rows: TickerRow[],
  tf: OiTimeframe,
  domain: RankDomain,
  category: string,
  positive: boolean,
  unit: "pct" | "mk",
): MatrixRow[] {
  const picked = eligible(rows)
    .filter((r) => {
      const m = getRankMetric(r, tf, domain);
      return positive ? m.change_rate > 0 : m.change_rate < 0;
    })
    .sort((a, b) => absRankScore(getRankMetric(b, tf, domain), unit) - absRankScore(getRankMetric(a, tf, domain), unit))
    .slice(0, TOP);

  return picked.map((r, i) => {
    const m = getRankMetric(r, tf, domain);
    const display = displayScore(m, positive, unit);
    const bar = absRankScore(m, unit);
    return toMatrixRow(r, i + 1, display, bar, category, tf);
  });
}

function deriveStrengthList(
  rows: TickerRow[],
  tf: OiTimeframe,
  domain: RankDomain,
  category: string,
  positive: boolean,
  unit: "pct" | "mk",
): MatrixRow[] {
  const picked = eligible(rows)
    .filter((r) => {
      const m = getRankMetric(r, tf, domain);
      return positive ? m.change_rate > 0 : m.change_rate < 0;
    })
    .sort((a, b) => {
      if (positive) {
        return (
          getRankMetric(b, tf, domain).intensity_score -
          getRankMetric(a, tf, domain).intensity_score
        );
      }
      return (
        absRankScore(getRankMetric(b, tf, domain), unit) -
        absRankScore(getRankMetric(a, tf, domain), unit)
      );
    })
    .slice(0, TOP);

  return picked.map((r, i) => {
    const m = getRankMetric(r, tf, domain);
    const display = displayScore(m, positive, unit);
    const bar = positive ? m.intensity_score : absRankScore(m, unit);
    return toMatrixRow(r, i + 1, display, bar, category, tf);
  });
}

// ── 涨跌幅（单位 %）──

export function deriveGainersMagnitude(rows: TickerRow[], tf: OiTimeframe) {
  return deriveMagnitudeList(rows, tf, "price", "gainers_magnitude", true, "pct");
}

export function deriveLosersMagnitude(rows: TickerRow[], tf: OiTimeframe) {
  return deriveMagnitudeList(rows, tf, "price", "losers_magnitude", false, "pct");
}

export function deriveGainersStrength(rows: TickerRow[], tf: OiTimeframe) {
  return deriveStrengthList(rows, tf, "price", "gainers_strength", true, "pct");
}

export function deriveLosersStrength(rows: TickerRow[], tf: OiTimeframe) {
  return deriveStrengthList(rows, tf, "price", "losers_strength", false, "pct");
}

// ── 持仓（量级 M/K，强度 %）──

export function deriveOiPumps(rows: TickerRow[], tf: OiTimeframe) {
  return deriveMagnitudeList(rows, tf, "oi", "oi_pumps", true, "mk");
}

export function deriveOiDumps(rows: TickerRow[], tf: OiTimeframe) {
  return deriveMagnitudeList(rows, tf, "oi", "oi_dumps", false, "mk");
}

export function deriveOiPumpStrength(rows: TickerRow[], tf: OiTimeframe) {
  return deriveStrengthList(rows, tf, "oi", "oi_pump_strength", true, "pct");
}

export function deriveOiDumpStrength(rows: TickerRow[], tf: OiTimeframe) {
  return deriveStrengthList(rows, tf, "oi", "oi_dump_strength", false, "pct");
}

// ── 合约流向（M/K）──

export function deriveContractInflow(rows: TickerRow[], tf: OiTimeframe) {
  return deriveMagnitudeList(rows, tf, "contract_flow", "contract_inflow", true, "mk");
}

export function deriveContractOutflow(rows: TickerRow[], tf: OiTimeframe) {
  return deriveMagnitudeList(rows, tf, "contract_flow", "contract_outflow", false, "mk");
}

export function deriveContractInflowStrength(rows: TickerRow[], tf: OiTimeframe) {
  return deriveStrengthList(rows, tf, "contract_flow", "contract_inflow_strength", true, "mk");
}

export function deriveContractOutflowStrength(rows: TickerRow[], tf: OiTimeframe) {
  return deriveStrengthList(rows, tf, "contract_flow", "contract_outflow_strength", false, "mk");
}

// ── 现货流向（M/K）──

export function deriveSpotInflow(rows: TickerRow[], tf: OiTimeframe) {
  return deriveMagnitudeList(rows, tf, "spot_flow", "spot_inflow", true, "mk");
}

export function deriveSpotOutflow(rows: TickerRow[], tf: OiTimeframe) {
  return deriveMagnitudeList(rows, tf, "spot_flow", "spot_outflow", false, "mk");
}

export function deriveSpotInflowStrength(rows: TickerRow[], tf: OiTimeframe) {
  return deriveStrengthList(rows, tf, "spot_flow", "spot_inflow_strength", true, "mk");
}

export function deriveSpotOutflowStrength(rows: TickerRow[], tf: OiTimeframe) {
  return deriveStrengthList(rows, tf, "spot_flow", "spot_outflow_strength", false, "mk");
}

// ── 右侧资金倾向 ──

function toBiasItem(
  row: TickerRow,
  rank: number,
  score: number,
  direction: "inflow" | "outflow",
): CapitalBiasItem {
  return {
    symbol: row.symbol,
    rank,
    direction,
    direction_label: direction === "inflow" ? "流入" : "流出",
    score,
    score_fmt: fmtNum(score),
  };
}

export function deriveCapitalConfluence(rows: TickerRow[], tf: OiTimeframe): CapitalBiasItem[] {
  const scored = eligible(rows)
    .map((row) => {
      const contract = getRankMetric(row, tf, "contract_flow").magnitude_usd;
      const spot = getRankMetric(row, tf, "spot_flow").magnitude_usd;
      const oiDelta = getOiWindow(row, tf).delta_usd;

      let score = 0;
      let direction: "inflow" | "outflow" = "inflow";

      if (contract * spot > 0) {
        score = Math.min(Math.abs(contract), Math.abs(spot));
        direction = contract > 0 ? "inflow" : "outflow";
      }
      if (oiDelta < 0 && spot > 0) {
        const rev = Math.abs(spot) + (contract < 0 ? Math.abs(contract) * 0.5 : 0);
        if (rev > score) {
          score = rev;
          direction = "inflow";
        }
      } else if (oiDelta > 0 && spot < 0) {
        const rev = Math.abs(spot) + (contract > 0 ? Math.abs(contract) * 0.5 : 0);
        if (rev > score) {
          score = rev;
          direction = "outflow";
        }
      }

      return { row, score, direction };
    })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, TOP);

  return scored.map((x, i) => toBiasItem(x.row, i + 1, x.score, x.direction));
}

export function deriveCapitalIntensity(rows: TickerRow[], tf: OiTimeframe): CapitalBiasItem[] {
  const scored = eligible(rows)
    .map((row) => {
      const contract = getRankMetric(row, tf, "contract_flow").magnitude_usd;
      const spot = getRankMetric(row, tf, "spot_flow").magnitude_usd;
      const total = contract + spot;
      const score = Math.abs(contract) + Math.abs(spot);
      const direction: "inflow" | "outflow" = total >= 0 ? "inflow" : "outflow";
      return { row, score, direction };
    })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, TOP);

  return scored.map((x, i) => toBiasItem(x.row, i + 1, x.score, x.direction));
}

export function deriveAllLists(rows: TickerRow[], tf: OiTimeframe) {
  return {
    price: {
      gainersMagnitude: deriveGainersMagnitude(rows, tf),
      losersMagnitude: deriveLosersMagnitude(rows, tf),
      gainersStrength: deriveGainersStrength(rows, tf),
      losersStrength: deriveLosersStrength(rows, tf),
    },
    oi: {
      posMagnitude: deriveOiPumps(rows, tf),
      negMagnitude: deriveOiDumps(rows, tf),
      posStrength: deriveOiPumpStrength(rows, tf),
      negStrength: deriveOiDumpStrength(rows, tf),
    },
    contract: {
      inMagnitude: deriveContractInflow(rows, tf),
      outMagnitude: deriveContractOutflow(rows, tf),
      inStrength: deriveContractInflowStrength(rows, tf),
      outStrength: deriveContractOutflowStrength(rows, tf),
    },
    spot: {
      inMagnitude: deriveSpotInflow(rows, tf),
      outMagnitude: deriveSpotOutflow(rows, tf),
      inStrength: deriveSpotInflowStrength(rows, tf),
      outStrength: deriveSpotOutflowStrength(rows, tf),
    },
    capitalConfluence: deriveCapitalConfluence(rows, tf),
    capitalIntensity: deriveCapitalIntensity(rows, tf),
  };
}
