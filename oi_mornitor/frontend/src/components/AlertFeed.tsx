import { memo, useMemo } from "react";
import type { TickerRow } from "../types";
import { deriveOiAlerts, type OiAlertItem } from "../utils/deriveOiAlerts";
import { fmtDelta, fmtPct } from "../utils/format";
import { coinInitial, displaySymbol } from "../utils/symbol";

interface Props {
  rows: TickerRow[];
  scanTs: number;
  poolSize: number;
  thresholds: { oi_usd_limit: number; oi_pct_limit: number };
}

function formatClock(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function windowLabel(window: OiAlertItem["window"]): string {
  return window === "5m" ? "5分钟内" : "15分钟内";
}

const AlertCard = memo(function AlertCard({
  item,
  timeLabel,
}: {
  item: OiAlertItem;
  timeLabel: string;
}) {
  const { row, window, deltaUsd, pct, isPump, isSuppressed } = item;

  return (
    <article
      className={`alert-card ${isPump ? "pump" : "dump"} ${isSuppressed ? "suppressed" : ""}`}
    >
      <div className="alert-card-row">
        <time className="alert-ts">{timeLabel}</time>
        <div className="alert-card-body">
          <div className="alert-card-head">
            <div className="alert-coin">
              <span className="coin-avatar">{coinInitial(row.symbol)}</span>
              <span className="alert-symbol">${displaySymbol(row.symbol)}</span>
            </div>
            <span className={`alert-type ${isPump ? "pump" : "dump"}`}>
              OI {isPump ? "暴涨" : "暴跌"}
              {isSuppressed ? " · 已抑制" : ""}
            </span>
          </div>
          <p className={`alert-desc ${isPump ? "pos" : "neg"}`}>
            {windowLabel(window)} oi {fmtDelta(deltaUsd)} ({fmtPct(pct)})
          </p>
          <div className="alert-tags">
            {row.individual_strength_score != null && (
              <span className="alert-tag">自身强度 #{row.individual_strength_score.toFixed(0)}</span>
            )}
            {row.global_intensity_rank != null && (
              <span className="alert-tag">全场强度 #{row.global_intensity_rank}</span>
            )}
            {row.global_volume_rank != null && (
              <span className="alert-tag">全场量级 #{row.global_volume_rank}</span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
});

export const AlertFeed = memo(function AlertFeed({
  rows,
  scanTs,
  poolSize,
  thresholds,
}: Props) {
  const alerts = useMemo(
    () => deriveOiAlerts(rows, thresholds),
    [rows, thresholds],
  );
  const timeLabel = formatClock(scanTs);

  return (
    <aside className="panel alert-feed">
      <div className="panel-title">
        <span className="alert-feed-title">
          异动监控
          <span className="alert-feed-info" title="5m / 15m OI 暴涨暴跌实时推送">
            ⓘ
          </span>
        </span>
        <span className="panel-count">更新 {timeLabel}</span>
      </div>

      <div className="alert-scanner">
        <span className="alert-scanner-label">AI 全市场扫描</span>
        <span className="alert-scanner-meta">{poolSize}+ 币种</span>
      </div>

      <div className="alert-feed-scroll">
        {alerts.length === 0 ? (
          <div className="panel-empty">暂无异动 · 持续扫描中</div>
        ) : (
          alerts.map((item) => (
            <AlertCard key={item.id} item={item} timeLabel={timeLabel} />
          ))
        )}
      </div>
    </aside>
  );
});
