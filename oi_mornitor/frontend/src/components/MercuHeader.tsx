import { memo, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import type { PoolMeta } from "../types";

interface Props {
  online: boolean;
  scanTs: number;
  poolMeta?: PoolMeta;
  poolSize: number;
}

const NAV = [
  { to: "/", label: "雷达", end: true },
  { to: "/patterns", label: "形态", end: false },
] as const;

export const MercuHeader = memo(function MercuHeader({
  online,
  scanTs,
  poolMeta,
  poolSize,
}: Props) {
  const [clock, setClock] = useState("");

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      const h = String(now.getHours()).padStart(2, "0");
      const m = String(now.getMinutes()).padStart(2, "0");
      const s = String(now.getSeconds()).padStart(2, "0");
      setClock(`${h}:${m}:${s}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const scanLabel = scanTs
    ? new Date(scanTs * 1000).toLocaleTimeString("zh-CN", { hour12: false })
    : "—";

  const poolLabel = poolMeta
    ? `大象${poolMeta.heavyweight_count ?? 0}·中场${poolMeta.midweight_count ?? 0}·监控${poolMeta.eligible_count ?? poolSize}`
    : `监控 ${poolSize}`;

  const sourceId = poolMeta?.data_source || "binance";
  const sourceLabel = poolMeta?.data_source_label || "Binance";
  const isFallback = sourceId !== "binance";

  return (
    <header className="mercu-header">
      <div className="mercu-header-left">
        <div className="mercu-logo">MERCU</div>
        <nav className="mercu-nav">
          {NAV.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => `mercu-nav-item${isActive ? " active" : ""}`}
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <span className="mercu-pool-badge">{poolLabel}</span>
        <span
          className={`mercu-source-badge${isFallback ? " fallback" : ""}`}
          title={
            isFallback
              ? `备选 · ${poolMeta?.fallback_reason || "限流/封禁"} · 链 ${(poolMeta?.fallback_chain || []).join("→")}`
              : `主源 Binance · 备选 ${(poolMeta?.fallback_chain || ["bybit", "okx", "bitget", "gate"]).join("→")}`
          }
        >
          源 {isFallback ? sourceLabel : "Binance"}
        </span>
      </div>
      <div className="mercu-header-right">
        <div className="mercu-status">
          <span className={`live-pill ${online ? "on" : "off"}`}>
            <span className="live-dot" />
            {online ? "LIVE" : "OFF"}
          </span>
          <span className="mercu-clock">UTC+8 {clock}</span>
          <span className="mercu-scan">扫描 {scanLabel}</span>
        </div>
      </div>
    </header>
  );
});
