import { memo } from "react";
import type { OiTimeframe } from "../types";
import { TIMEFRAMES } from "../utils/timeframe";

interface Props {
  timeframe: OiTimeframe;
  onTimeframeChange: (tf: OiTimeframe) => void;
}

export const MercuTimeframes = memo(function MercuTimeframes({
  timeframe,
  onTimeframeChange,
}: Props) {
  return (
    <div className="mercu-timeframes">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          type="button"
          className={`tf-btn ${tf === timeframe ? "active" : ""}`}
          onClick={() => onTimeframeChange(tf)}
        >
          {tf}
        </button>
      ))}
    </div>
  );
});
