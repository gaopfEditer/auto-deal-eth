import { memo } from "react";
import type { CapitalBiasItem, GlobalMeta } from "../types";
import { fmtDelta } from "../utils/format";
import { coinInitial, displaySymbol } from "../utils/symbol";

interface Props {
  meta?: GlobalMeta;
  capitalConfluence: CapitalBiasItem[];
  capitalIntensity: CapitalBiasItem[];
  biasTf: string;
}

const BiasList = memo(function BiasList({
  title,
  items,
}: {
  title: string;
  items: CapitalBiasItem[];
}) {
  return (
    <section className="bias-section">
      <div className="bias-section-head">{title}</div>
      <ul className="bias-list">
        {items.length === 0 ? (
          <li className="bias-empty">暂无信号</li>
        ) : (
          items.map((item) => (
            <li key={`${title}-${item.symbol}`} className="bias-item">
              <span className="bias-rank">{item.rank}</span>
              <span className="bias-avatar">{coinInitial(item.symbol)}</span>
              <span className="bias-symbol">${displaySymbol(item.symbol)}</span>
              <span className={`bias-tag ${item.direction}`}>{item.direction_label}</span>
              <span className={`bias-score ${item.direction === "inflow" ? "pos" : "neg"}`}>
                {item.score_fmt ?? fmtDelta(item.score)}
              </span>
            </li>
          ))
        )}
      </ul>
    </section>
  );
});

export const GlobalTrendPanel = memo(function GlobalTrendPanel({
  meta,
  capitalConfluence,
  capitalIntensity,
  biasTf,
}: Props) {
  const bias = meta?.long_short_bias;
  const regime = meta?.risk_regime ?? "mixed";
  const net = meta?.global_oi_net_inflow ?? 0;

  return (
    <aside className="panel global-panel">
      <div className="panel-title">
        <span>资金倾向性</span>
        <span className="panel-title-sub">{biasTf}</span>
      </div>

      <BiasList title="资金合流" items={capitalConfluence} />
      <BiasList title="资金力度" items={capitalIntensity} />

      <div className="panel-title section-gap">
        <span>全场态势</span>
      </div>
      <div className={`global-trend-card ${regime}`}>
        <div className="trend-regime">{meta?.risk_regime_label ?? "Mixed"}</div>
        <div className="trend-bias">{bias?.label ?? "多空力量均衡"}</div>
        <div className={`trend-inflow ${net >= 0 ? "pos" : "neg"}`}>
          5m 净流入 {meta?.global_oi_net_inflow_fmt ?? fmtDelta(net)}
        </div>
        <div className="trend-stats">
          <div>
            <span className="k">多头建仓</span>
            <span className="v pos">{bias?.long_build_count ?? 0}</span>
          </div>
          <div>
            <span className="k">空头压制</span>
            <span className="v neg">{bias?.short_suppress_count ?? 0}</span>
          </div>
          <div>
            <span className="k">监控池</span>
            <span className="v">{meta?.pool_monitored ?? 0}/{meta?.pool_size ?? 40}</span>
          </div>
        </div>
      </div>
    </aside>
  );
});
