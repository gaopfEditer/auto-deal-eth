import { useMemo, useState } from "react";
import { AlertFeed } from "../components/AlertFeed";
import { BreakoutToastStack } from "../components/BreakoutToastStack";
import { GlobalTrendPanel } from "../components/GlobalTrendPanel";
import { MarketMatrixGrid } from "../components/MarketMatrixGrid";
import { MercuHeader } from "../components/MercuHeader";
import { ToastStack } from "../components/ToastStack";
import { useRadarSSE } from "../hooks/useRadarSSE";
import type { OiTimeframe } from "../types";
import { deriveAllLists } from "../utils/deriveLists";

export function RadarPage() {
  const { snapshot, online } = useRadarSSE();
  const [timeframe, setTimeframe] = useState<OiTimeframe>("15m");
  const {
    all_tickers: all,
    hot_tickers: hot,
    meta,
    scan_ts: scanTs,
    pool_size: poolSize,
    thresholds,
    breakout_alerts: breakoutAlerts = [],
  } = snapshot;

  const lists = useMemo(() => deriveAllLists(all, timeframe), [all, timeframe]);

  return (
    <div className="mercu-app">
      <MercuHeader
        online={online}
        scanTs={scanTs}
        poolMeta={snapshot.pool_meta}
        poolSize={snapshot.pool_size}
      />
      <div className="mercu-body">
        <AlertFeed rows={all} scanTs={scanTs} poolSize={poolSize} thresholds={thresholds} />
        <MarketMatrixGrid
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
          price={lists.price}
          oi={lists.oi}
          contract={lists.contract}
          spot={lists.spot}
          takerFlowStatus={snapshot.pool_meta?.taker_flow_status}
        />
        <GlobalTrendPanel
          meta={meta}
          capitalConfluence={lists.capitalConfluence}
          capitalIntensity={lists.capitalIntensity}
          biasTf={timeframe}
        />
      </div>
      <ToastStack hot={hot} scanTs={scanTs} />
      <BreakoutToastStack alerts={breakoutAlerts} scanTs={scanTs} />
    </div>
  );
}
