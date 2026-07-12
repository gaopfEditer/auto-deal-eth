import { memo, type CSSProperties } from "react";
import type { OiTimeframe } from "../types";
import type { MatrixRow } from "../types";
import { fmtMk, fmtPct } from "../utils/format";
import { coinInitial, displaySymbol } from "../utils/symbol";
import { MercuTimeframes } from "./MercuTimeframes";

type ValueMode = "pct" | "mk";

interface RankListProps {
  title: string;
  subtitle: string;
  rows: MatrixRow[];
  valueMode: ValueMode;
  /** 负向榜（流出/跌幅）：强制红色 */
  negativeBoard?: boolean;
}

function barValue(row: MatrixRow): number {
  return row.matrix_bar ?? Math.abs(row.matrix_score);
}

function formatValue(v: number, mode: ValueMode): string {
  if (mode === "pct") return fmtPct(v);
  return fmtMk(v);
}

const RankList = memo(function RankList({
  title,
  subtitle,
  rows,
  valueMode,
  negativeBoard = false,
}: RankListProps) {
  const maxBar = Math.max(...rows.map((r) => barValue(r)), 1);

  return (
    <section className="rank-panel">
      <div className="rank-panel-head">
        <h3>{title}</h3>
        <span>{subtitle}</span>
      </div>
      <ul className="rank-list">
        {rows.length === 0 ? (
          <li className="rank-empty">暂无数据</li>
        ) : (
          rows.map((row) => {
            const v = row.matrix_score;
            const barPct = (barValue(row) / maxBar) * 100;
            const tone = negativeBoard ? "down" : "up";

            return (
              <li
                key={`${title}-${subtitle}-${row.symbol}`}
                className={`rank-item rank-item-bg ${tone}`}
                style={{ "--bar-pct": `${Math.max(barPct, 6)}%` } as CSSProperties}
              >
                <span className="rank-badge">{row.matrix_rank}</span>
                <span className="rank-coin-avatar">{coinInitial(row.symbol)}</span>
                <span className="rank-symbol">${displaySymbol(row.symbol)}</span>
                <span className={`rank-value ${negativeBoard ? "neg" : "pos"}`}>
                  {formatValue(v, valueMode)}
                </span>
              </li>
            );
          })
        )}
      </ul>
    </section>
  );
});

interface Block {
  gainersMagnitude: MatrixRow[];
  losersMagnitude: MatrixRow[];
  gainersStrength: MatrixRow[];
  losersStrength: MatrixRow[];
}

interface OiBlock {
  posMagnitude: MatrixRow[];
  negMagnitude: MatrixRow[];
  posStrength: MatrixRow[];
  negStrength: MatrixRow[];
}

interface FlowBlock {
  inMagnitude: MatrixRow[];
  outMagnitude: MatrixRow[];
  inStrength: MatrixRow[];
  outStrength: MatrixRow[];
}

interface Props {
  timeframe: OiTimeframe;
  onTimeframeChange: (tf: OiTimeframe) => void;
  price: Block;
  oi: OiBlock;
  contract: FlowBlock;
  spot: FlowBlock;
}

export const MarketMatrixGrid = memo(function MarketMatrixGrid({
  timeframe,
  onTimeframeChange,
  price,
  oi,
  contract,
  spot,
}: Props) {
  return (
    <main className="panel matrix-center">
      <div className="matrix-center-head">
        <h2>热钱观察榜单</h2>
        <MercuTimeframes timeframe={timeframe} onTimeframeChange={onTimeframeChange} />
      </div>

      <div className="matrix-quadrants">
        <div className="matrix-quadrant-grid">
          <RankList title="涨幅榜" subtitle="量级榜" rows={price.gainersMagnitude} valueMode="pct" />
          <RankList title="跌幅榜" subtitle="量级榜" rows={price.losersMagnitude} valueMode="pct" negativeBoard />
          <RankList title="涨幅榜" subtitle="强度榜" rows={price.gainersStrength} valueMode="pct" />
          <RankList title="跌幅榜" subtitle="强度榜" rows={price.losersStrength} valueMode="pct" negativeBoard />
        </div>

        <div className="matrix-quadrant-grid">
          <RankList title="持仓榜" subtitle="正 · 量级榜" rows={oi.posMagnitude} valueMode="mk" />
          <RankList title="持仓榜" subtitle="负 · 量级榜" rows={oi.negMagnitude} valueMode="mk" negativeBoard />
          <RankList title="持仓榜" subtitle="正 · 强度榜" rows={oi.posStrength} valueMode="pct" />
          <RankList title="持仓榜" subtitle="负 · 强度榜" rows={oi.negStrength} valueMode="pct" negativeBoard />
        </div>

        <div className="matrix-quadrant-grid">
          <RankList title="主力合约" subtitle="流入 · 量级榜" rows={contract.inMagnitude} valueMode="mk" />
          <RankList title="主力合约" subtitle="流出 · 量级榜" rows={contract.outMagnitude} valueMode="mk" negativeBoard />
          <RankList title="主力合约" subtitle="流入 · 强度榜" rows={contract.inStrength} valueMode="mk" />
          <RankList title="主力合约" subtitle="流出 · 强度榜" rows={contract.outStrength} valueMode="mk" negativeBoard />
        </div>

        <div className="matrix-quadrant-grid">
          <RankList title="主力现货" subtitle="流入 · 量级榜" rows={spot.inMagnitude} valueMode="mk" />
          <RankList title="主力现货" subtitle="流出 · 量级榜" rows={spot.outMagnitude} valueMode="mk" negativeBoard />
          <RankList title="主力现货" subtitle="流入 · 强度榜" rows={spot.inStrength} valueMode="mk" />
          <RankList title="主力现货" subtitle="流出 · 强度榜" rows={spot.outStrength} valueMode="mk" negativeBoard />
        </div>
      </div>
    </main>
  );
});
