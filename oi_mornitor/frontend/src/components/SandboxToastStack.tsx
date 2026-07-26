import { memo, useEffect, useRef, useState } from "react";
import type { PatternAlert } from "../types";
import { coinInitial, displaySymbol } from "../utils/symbol";

interface ToastItem {
  id: string;
  alert: PatternAlert;
  createdAt: number;
}

interface Props {
  alerts: PatternAlert[];
  scanTs: number;
  onOpen?: (symbol: string) => void;
}

const TOAST_TTL_MS = 22000;

const TYPE_LABEL: Record<string, string> = {
  entry: "沙盒入场",
  exit: "沙盒平仓",
  trail: "沙盒移止损",
  partial: "沙盒减仓",
  card_watch: "卡片接入",
  card_near: "卡片近场",
  card_order: "卡片挂单",
};

export const SandboxToastStack = memo(function SandboxToastStack({
  alerts,
  scanTs,
  onOpen,
}: Props) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const seenRef = useRef<Set<string>>(new Set());
  const scanRef = useRef(0);

  useEffect(() => {
    if (!scanTs || scanTs === scanRef.current) return;
    scanRef.current = scanTs;

    const fresh = alerts.filter((a) => {
      const key = `${a.type}:${a.symbol}:${a.kline_close_time}:${a.message}`;
      if (seenRef.current.has(key)) return false;
      seenRef.current.add(key);
      return true;
    });
    if (!fresh.length) return;

    const now = Date.now();
    setToasts((prev) =>
      [
        ...fresh.map((alert) => ({
          id: `${alert.type}-${alert.symbol}-${alert.kline_close_time}-${now}`,
          alert,
          createdAt: now,
        })),
        ...prev,
      ].slice(0, 8),
    );
  }, [alerts, scanTs]);

  useEffect(() => {
    if (!toasts.length) return;
    const id = setInterval(() => {
      const cutoff = Date.now() - TOAST_TTL_MS;
      setToasts((prev) => prev.filter((t) => t.createdAt > cutoff));
    }, 1000);
    return () => clearInterval(id);
  }, [toasts.length]);

  const dismiss = (id: string) => setToasts((prev) => prev.filter((t) => t.id !== id));

  if (!toasts.length) return null;

  return (
    <div className="pattern-toast-stack sandbox-toast-stack">
      {toasts.map(({ id, alert }) => (
        <div
          key={id}
          className={`toast-card sandbox-${alert.type === "exit" ? (Number(alert.pnl_usd) >= 0 ? "win" : "loss") : "signal"}`}
        >
          <button type="button" className="toast-close" onClick={() => dismiss(id)} aria-label="关闭">
            ×
          </button>
          <div className="toast-head">
            <span className="coin-avatar">{coinInitial(alert.symbol)}</span>
            <div>
              <div className="toast-title">
                ${displaySymbol(alert.symbol)} · {TYPE_LABEL[alert.type] ?? alert.status_label}
              </div>
              <div className="toast-sub">
                逻辑{alert.logic ?? "—"} · {alert.side ?? "—"} · {alert.interval}
              </div>
              <div className="toast-sub">{alert.message}</div>
              {alert.pnl_usd != null && (
                <div className="toast-sub">
                  PnL {alert.pnl_usd >= 0 ? "+" : ""}
                  {alert.pnl_usd.toFixed(2)}U ({alert.pnl_pct?.toFixed(2)}%)
                </div>
              )}
            </div>
          </div>
          <button
            type="button"
            className="toast-action"
            onClick={() => {
              onOpen?.(alert.symbol);
              dismiss(id);
            }}
          >
            查看 K 线
          </button>
        </div>
      ))}
    </div>
  );
});
