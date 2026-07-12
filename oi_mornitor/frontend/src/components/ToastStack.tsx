import { memo, useEffect, useRef, useState } from "react";
import type { TickerRow } from "../types";
import { fmtDelta, fmtPct } from "../utils/format";
import { coinInitial, displaySymbol } from "../utils/symbol";

interface ToastItem {
  id: string;
  row: TickerRow;
  createdAt: number;
}

interface Props {
  hot: TickerRow[];
  scanTs: number;
}

const TOAST_TTL_MS = 12000;

export const ToastStack = memo(function ToastStack({ hot, scanTs }: Props) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const seenRef = useRef<Set<string>>(new Set());
  const scanRef = useRef(0);

  useEffect(() => {
    if (!scanTs || scanTs === scanRef.current) return;
    scanRef.current = scanTs;

    const alerts = hot.filter((r) => r.is_alert);
    const fresh = alerts.filter((r) => !seenRef.current.has(r.symbol));
    if (!fresh.length) return;

    fresh.forEach((r) => seenRef.current.add(r.symbol));
    const now = Date.now();
    setToasts((prev) => [
      ...fresh.map((row) => ({
        id: `${row.symbol}-${now}`,
        row,
        createdAt: now,
      })),
      ...prev,
    ].slice(0, 5));
  }, [hot, scanTs]);

  useEffect(() => {
    if (!toasts.length) return;
    const id = setInterval(() => {
      const cutoff = Date.now() - TOAST_TTL_MS;
      setToasts((prev) => prev.filter((t) => t.createdAt > cutoff));
    }, 1000);
    return () => clearInterval(id);
  }, [toasts.length]);

  const dismiss = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  if (!toasts.length) return null;

  return (
    <div className="toast-stack">
      {toasts.map(({ id, row }) => {
        const isPump = row.status === "pump" || row.delta_5m_usd > 0;
        return (
          <div key={id} className={`toast-card ${isPump ? "pump" : "dump"}`}>
            <button type="button" className="toast-close" onClick={() => dismiss(id)} aria-label="关闭">
              ×
            </button>
            <div className="toast-head">
              <span className="coin-avatar">{coinInitial(row.symbol)}</span>
              <div>
                <div className="toast-title">
                  ${displaySymbol(row.symbol)} · 全场强度榜第 {row.global_intensity_rank ?? "—"} 名
                </div>
                <div className="toast-sub">
                  5分钟内 OI {isPump ? "暴涨" : "暴跌"} {fmtPct(row.pct_5m)} · {fmtDelta(row.delta_5m_usd)}
                </div>
              </div>
            </div>
            <button type="button" className="toast-action">看详情</button>
          </div>
        );
      })}
    </div>
  );
});
