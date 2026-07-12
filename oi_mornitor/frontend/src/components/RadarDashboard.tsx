import { memo } from "react";
import type { TickerRow } from "../types";
import { deltaClass, fmtDelta, fmtNum, fmtPct, statusLabel } from "../utils/format";

interface Props {
  online: boolean;
  scanTs: number;
  hotCount: number;
  poolSize: number;
  usdLimit: number;
  pctLimit: number;
}

export const Header = memo(function Header({
  online,
  scanTs,
  hotCount,
  poolSize,
  usdLimit,
  pctLimit,
}: Props) {
  const ts = scanTs
    ? new Date(scanTs * 1000).toLocaleString("zh-CN", { hour12: false })
    : "—";

  return (
    <header className="header">
      <div className="brand">
        <span className="pulse-dot" />
        <h1>OI 动态热钱雷达</h1>
        <span className="badge">Binance USDT-M · Top 40</span>
      </div>
      <div className="meta">
        <div className="meta-item">
          <span className="label">最近扫描</span>
          <span className="value">{ts}</span>
        </div>
        <div className="meta-item">
          <span className="label">异动 / 监控</span>
          <span className="value hot">
            {hotCount} / {poolSize}
          </span>
        </div>
        <div className="meta-item">
          <span className="label">阈值</span>
          <span className="value">
            ≥${fmtNum(usdLimit)} · ≥{pctLimit}%
          </span>
        </div>
        <div className={`conn ${online ? "online" : "offline"}`}>
          {online ? "LIVE" : "OFFLINE"}
        </div>
      </div>
    </header>
  );
});

interface RadarProps {
  hot: TickerRow[];
}

export const RadarPanel = memo(function RadarPanel({ hot }: RadarProps) {
  return (
    <section className="radar-panel">
      <div className="radar-ring ring-1" />
      <div className="radar-ring ring-2" />
      <div className="radar-ring ring-3" />
      <div className="radar-sweep" />
      <div className="radar-blips">
        {hot.map((row, i) => {
          const angle = (i / Math.max(hot.length, 1)) * Math.PI * 2 - Math.PI / 2;
          const radius = 38 + (i % 3) * 12;
          const x = 50 + Math.cos(angle) * radius;
          const y = 50 + Math.sin(angle) * radius;
          return (
            <div
              key={row.symbol}
              className={`blip ${row.status}`}
              style={{ left: `${x}%`, top: `${y}%` }}
              title={row.symbol}
            />
          );
        })}
      </div>
      <div className="radar-center">
        <div className="center-num">{hot.length}</div>
        <div className="center-label">HOT</div>
      </div>
    </section>
  );
});

const HotCard = memo(function HotCard({ row }: { row: TickerRow }) {
  return (
    <div className={`card ${row.status}`}>
      <div className="card-top">
        <div>
          <div className="card-symbol">{row.symbol}</div>
          <div className="card-rank">成交额 Top {row.volume_rank}</div>
        </div>
        <span className={`card-tag ${row.status}`}>{statusLabel(row.status)}</span>
      </div>
      <div className="card-metrics">
        <div className="metric">
          <span className="k">OI (USD)</span>
          <span className="v">{fmtNum(row.current_oi_usd)}</span>
        </div>
        <div className="metric">
          <span className="k">触发窗口</span>
          <span className="v">{row.triggered_windows?.join(" · ") || "—"}</span>
        </div>
        <div className="metric">
          <span className="k">5m Δ$</span>
          <span className={`v ${deltaClass(row.delta_5m_usd)}`}>
            {fmtDelta(row.delta_5m_usd)}
          </span>
        </div>
        <div className="metric">
          <span className="k">5m %</span>
          <span className={`v ${deltaClass(row.pct_5m)}`}>{fmtPct(row.pct_5m)}</span>
        </div>
        <div className="metric">
          <span className="k">Z-Score</span>
          <span className={`v ${row.is_historic_anomaly ? "pos" : ""}`}>
            {row.individual_strength_score != null ? row.individual_strength_score.toFixed(2) : "—"}
            {row.is_historic_anomaly ? " 💥" : ""}
          </span>
        </div>
        <div className="metric">
          <span className="k">全场强度#</span>
          <span className="v">{row.global_intensity_rank ?? "—"}</span>
        </div>
        <div className="metric">
          <span className="k">全场量级#</span>
          <span className="v">{row.global_volume_rank ?? "—"}</span>
        </div>
        <div className="metric">
          <span className="k">15m %</span>
          <span className={`v ${deltaClass(row.pct_15m)}`}>{fmtPct(row.pct_15m)}</span>
        </div>
      </div>
    </div>
  );
});

export const HotCards = memo(function HotCards({ hot }: { hot: TickerRow[] }) {
  if (!hot.length) {
    return (
      <section className="hot-cards">
        <div className="empty-state">当前无热钱异动 · 持续扫描中</div>
      </section>
    );
  }
  return (
    <section className="hot-cards">
      {hot.map((row) => (
        <HotCard key={row.symbol} row={row} />
      ))}
    </section>
  );
});

const TableRow = memo(function TableRow({ row }: { row: TickerRow }) {
  return (
    <tr className={row.is_hot ? "row-hot" : ""}>
      <td>{row.volume_rank}</td>
      <td>{row.symbol}</td>
      <td>{fmtNum(row.current_oi_usd)}</td>
      <td className={deltaClass(row.delta_5m_usd)}>{fmtDelta(row.delta_5m_usd)}</td>
      <td className={deltaClass(row.pct_5m)}>{fmtPct(row.pct_5m)}</td>
      <td className={deltaClass(row.delta_15m_usd)}>{fmtDelta(row.delta_15m_usd)}</td>
      <td className={deltaClass(row.pct_15m)}>{fmtPct(row.pct_15m)}</td>
      <td>{fmtNum(row.quote_volume)}</td>
      <td>{row.individual_strength_score != null ? row.individual_strength_score.toFixed(2) : "—"}</td>
      <td>{row.global_intensity_rank ?? "—"}</td>
      <td>{row.global_volume_rank ?? "—"}</td>
      <td>
        <span className={`status-pill ${row.status}`}>
          {row.is_suppressed ? "🔇抑制" : row.is_historic_anomaly ? "💥历史级" : statusLabel(row.status)}
        </span>
      </td>
    </tr>
  );
});

export const TickerTable = memo(function TickerTable({ rows }: { rows: TickerRow[] }) {
  const sorted = [...rows].sort((a, b) => a.volume_rank - b.volume_rank);
  return (
    <section className="table-section">
      <div className="table-head">
        <h2>候选池全览</h2>
        <span className="hint">5m / 1h OI 变动 · 成交额排名</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>币种</th>
              <th>OI (USD)</th>
              <th>5m Δ$</th>
              <th>5m %</th>
              <th>15m Δ$</th>
              <th>15m %</th>
              <th>24h 成交额</th>
              <th>Z</th>
              <th>强度#</th>
              <th>量级#</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <TableRow key={row.symbol} row={row} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
});
