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
}

const TOAST_TTL_MS = 20000;

export const PatternToastStack = memo(function PatternToastStack({ alerts, scanTs }: Props) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const seenRef = useRef<Set<string>>(new Set());
  const scanRef = useRef(0);

  useEffect(() => {
    if (!scanTs || scanTs === scanRef.current) return;
    scanRef.current = scanTs;

    const fresh = alerts.filter((a) => {
      const key = `${a.symbol}:${a.kline_close_time}`;
      if (seenRef.current.has(key)) return false;
      seenRef.current.add(key);
      return true;
    });
    if (!fresh.length) return;

    const now = Date.now();
    setToasts((prev) => [
      ...fresh.map((alert) => ({
        id: `${alert.symbol}-${alert.kline_close_time}`,
        alert,
        createdAt: now,
      })),
      ...prev,
    ].slice(0, 6));
  }, [alerts, scanTs]);

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
    <div className="pattern-toast-stack">
      {toasts.map(({ id, alert }) => (
        <div key={id} className="toast-card pattern-fire">
          <button type="button" className="toast-close" onClick={() => dismiss(id)} aria-label="关闭">
            ×
          </button>
          <div className="toast-head">
            <span className="coin-avatar">{coinInitial(alert.symbol)}</span>
            <div>
              <div className="toast-title">
                ${displaySymbol(alert.symbol)} · 形态多头爆发
              </div>
              <div className="toast-sub">{alert.status_label} · {alert.interval}</div>
              <div className="toast-sub">{alert.message}</div>
            </div>
          </div>
          <button type="button" className="toast-action">查看形态</button>
        </div>
      ))}
    </div>
  );
});
