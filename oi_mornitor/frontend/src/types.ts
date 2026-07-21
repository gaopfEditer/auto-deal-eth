export type OiTimeframe = "15m" | "30m" | "1h" | "4h" | "1d";

export interface OiWindowSnapshot {
  delta_usd: number;
  pct: number;
}

export interface FlowWindowSnapshot {
  net_usd: number;
  volume_usd: number;
}

export interface PriceWindowSnapshot {
  pct: number;
}

export type OiByTf = Record<OiTimeframe, OiWindowSnapshot>;
export type FlowByTf = Record<OiTimeframe, FlowWindowSnapshot>;
export type PriceByTf = Record<OiTimeframe, PriceWindowSnapshot>;

export interface RankMetricSnapshot {
  magnitude_usd: number;
  change_rate: number;
  z_score: number;
  intensity_score: number;
}

export type RankDomain = "price" | "oi" | "contract_flow" | "spot_flow";
export type RankByTf = Record<OiTimeframe, Record<RankDomain, RankMetricSnapshot>>;

export type TickerStatus = "pump" | "dump" | "normal" | "warming" | "suppressed";
export type OiTier = "heavyweight" | "midweight";

export interface TickerRow {
  symbol: string;
  volume_rank: number;
  quote_volume: number;
  last_price: number;
  current_oi: number;
  current_oi_usd: number;
  delta_5m_usd: number;
  pct_5m: number;
  delta_15m_usd: number;
  pct_15m: number;
  pct_price_5m?: number;
  price_change_pct_24h?: number;
  oi_tier?: OiTier;
  oi_by_tf?: Partial<OiByTf>;
  price_by_tf?: Partial<PriceByTf>;
  flow_by_tf?: Partial<FlowByTf>;
  spot_flow_by_tf?: Partial<FlowByTf>;
  rank_by_tf?: Partial<RankByTf>;
  status: TickerStatus;
  triggered_windows: string[];
  raw_triggered_windows?: string[];
  is_hot: boolean;
  is_alert: boolean;
  is_suppressed: boolean;
  alert_reason?: string;
  type: string;
  individual_strength_score: number | null;
  is_historic_anomaly: boolean;
  global_intensity_rank: number | null;
  global_volume_rank: number | null;
}

export interface MatrixRow {
  symbol: string;
  category: string;
  matrix_rank: number;
  matrix_score: number;
  matrix_bar?: number;
  last_price?: number;
  price_change_pct_24h: number;
  quote_volume: number;
  volume_rank?: number;
  current_oi_usd: number;
  delta_5m_usd: number;
  pct_5m: number;
  delta_15m_usd: number;
  pct_15m: number;
  global_intensity_rank: number | null;
  global_volume_rank: number | null;
}

export interface MarketMatrix {
  matrix_ts: number;
  scan_ts: number;
  top_n: number;
  refresh_sec: number;
  pool_eligible: number;
  top_gainers_oi: MatrixRow[];
  top_losers_oi: MatrixRow[];
  oi_pumps: MatrixRow[];
  oi_dumps: MatrixRow[];
}

export interface CapitalBiasItem {
  symbol: string;
  rank: number;
  direction: "inflow" | "outflow";
  direction_label: "流入" | "流出";
  score: number;
  score_fmt?: string;
}

export interface GlobalMeta {
  global_oi_net_inflow: number;
  global_oi_net_inflow_fmt: string;
  long_short_bias: {
    long_build_count: number;
    short_suppress_count: number;
    dominant: "long" | "short" | "neutral";
    label: string;
  };
  risk_regime: "risk_on" | "risk_off" | "mixed";
  risk_regime_label: string;
  pool_monitored: number;
  pool_size: number;
  capital_bias_tf?: string;
  capital_confluence?: CapitalBiasItem[];
  capital_intensity?: CapitalBiasItem[];
}

export interface PoolMeta {
  mode: string;
  data_source?: string;
  data_source_label?: string;
  fallback_reason?: string;
  fallback_chain?: string[];
  ticker_count?: number;
  heavyweight_count?: number;
  midweight_count?: number;
  excluded_sub_10m?: number;
  eligible_count?: number;
  tier_mid_min_usd?: number;
  tier_heavy_min_usd?: number;
  taker_flow_status?: "live" | "cached" | "unavailable" | string;
  proxy_disabled?: boolean;
}

export interface BreakoutAlert {
  symbol: string;
  type: "breakout_trigger";
  supply_wall: number;
  last_price: number;
  categories: string;
  category_labels: string[];
  matrix_tf: string;
  scan_ts: number;
  kline_close_time: number;
  message: string;
}

export interface PatternWatchItem {
  symbol: string;
  interval: string;
  added_at: number;
  pinned?: boolean;
  pinned_until?: number;
  pin_remaining_sec?: number;
}

export interface PatternState {
  symbol: string;
  interval: string;
  status: string;
  status_label: string;
  h_max?: number;
  lh_price?: number;
  l1?: number;
  hl?: number;
  trigger_price?: number;
  hh_price?: number;
  message?: string;
  updated_at?: number;
  trigger_emitted?: boolean;
}

export interface PatternAlert {
  symbol: string;
  type: string;
  interval: string;
  status?: string;
  status_label: string;
  lh_price?: number;
  hl?: number;
  trigger_price?: number;
  hh_price?: number;
  last_price?: number;
  price?: number;
  entry_price?: number;
  exit_price?: number;
  entry_time?: number;
  exit_time?: number;
  leverage?: number;
  side?: string;
  logic?: string;
  pnl_usd?: number;
  pnl_pct?: number;
  roe_pct?: number;
  message: string;
  scan_ts?: number;
  kline_close_time: number;
  events?: Array<Record<string, unknown>>;
  exit_code?: string;
  exit_label?: string;
}

export interface SandboxTrade {
  id?: number;
  symbol: string;
  side: string;
  logic: string;
  entry_price: number;
  exit_price: number;
  entry_time?: number;
  exit_time?: number;
  leverage?: number;
  pnl_usd: number;
  pnl_pct: number;
  roe_pct?: number;
  reason: string;
  day?: string;
  events?: Array<Record<string, unknown>>;
  is_partial?: number;
  entry_reason?: string;
  source?: string;
  source_label?: string;
  exit_code?: string;
  exit_label?: string;
  fee_usd?: number;
  fee_pct?: number;
  interval?: string;
  ref_intervals?: string[];
  ref_intervals_label?: string;
}

export interface SandboxStats {
  day: string;
  balance: number;
  open_positions: number;
  closed_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  pnl_usd: number;
  avg_pnl_pct: number;
  by_logic?: Record<string, { trades: number; wins: number; pnl_usd: number }>;
  recent_trades?: SandboxTrade[];
}

export interface SandboxPosition {
  id?: number;
  symbol: string;
  side: string;
  logic: string;
  size: number;
  entry_price: number;
  entry_time: number;
  sl: number;
  tp1?: number | null;
  tp2?: number | null;
  breakeven_armed: boolean;
  leverage?: number;
  module?: string;
  stage?: number;
  events?: Array<Record<string, unknown>>;
  highest_price?: number;
  lowest_price?: number;
  partial_done?: boolean;
  entry_reason?: string;
  source?: string;
  source_label?: string;
  exit_code?: string;
  exit_label?: string;
  interval?: string;
  ref_intervals?: string[];
  ref_intervals_label?: string;
}

export interface PatternPayload {
  scan_ts: number;
  watchlist: PatternWatchItem[];
  states: PatternState[];
  pattern_alerts: PatternAlert[];
  heavyweight_pool_size?: number;
  auto_pick_count?: number;
  watchlist_refresh_sec?: number;
  watchlist_refresh_tf?: string;
  last_watchlist_refresh_ts?: number;
  sandbox_enabled?: boolean;
  sandbox_day?: string;
  sandbox_pool?: string[];
  sandbox_pool_count?: number;
  sandbox_max_concurrent?: number;
  sandbox_positions?: SandboxPosition[];
  sandbox_alerts?: PatternAlert[];
  sandbox_stats?: SandboxStats;
  sandbox_trade_history?: SandboxTrade[];
  sandbox_scan_ts?: number;
}

export interface PatternCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface PatternChartMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowDown" | "arrowUp" | "circle";
  text: string;
  price?: number;
  kind?: string;
}

export interface PatternPriceLine {
  kind: string;
  price: number;
  color: string;
  title: string;
}

export interface PatternChartAnalysis {
  status?: string;
  status_label?: string;
  message?: string;
  h_max?: number;
  lh_price?: number;
  l1?: number;
  hl?: number;
  trigger_price?: number;
  hh_price?: number;
  last_price?: number;
  bb_wick_top?: boolean;
  macd_bull?: boolean;
  macd_top_weak?: boolean;
}

export interface PatternChartData {
  ok: boolean;
  symbol: string;
  interval: string;
  candles: PatternCandle[];
  markers: PatternChartMarker[];
  price_lines: PatternPriceLine[];
  bb: {
    upper: { time: number; value: number }[];
    mid?: { time: number; value: number }[];
    lower: { time: number; value: number }[];
  };
  vegas?: {
    filter?: { time: number; value: number }[];
    a1?: { time: number; value: number }[];
    a2?: { time: number; value: number }[];
    b1?: { time: number; value: number }[];
    b2?: { time: number; value: number }[];
  };
  macd?: {
    line?: { time: number; value: number }[];
    signal?: { time: number; value: number }[];
    hist?: { time: number; value: number }[];
  };
  analysis: PatternChartAnalysis;
  state: PatternState;
  partial?: boolean;
  has_more?: boolean;
  ticker?: {
    last_price?: number;
    price_change_pct_24h?: number;
    current_oi_usd?: number;
    quote_volume?: number;
    oi_tier?: string;
  };
  error?: string;
}

export interface RadarSnapshot {
  scan_ts: number;
  meta?: GlobalMeta;
  pool_meta?: PoolMeta;
  hot_tickers: TickerRow[];
  all_tickers: TickerRow[];
  market_matrix?: MarketMatrix;
  breakout_alerts?: BreakoutAlert[];
  pattern?: PatternPayload;
  pool_size: number;
  thresholds: {
    oi_usd_limit: number;
    oi_pct_limit: number;
  };
}

export const EMPTY_SNAPSHOT: RadarSnapshot = {
  scan_ts: 0,
  meta: undefined,
  pool_meta: undefined,
  hot_tickers: [],
  all_tickers: [],
  market_matrix: undefined,
  breakout_alerts: [],
  pattern: { scan_ts: 0, watchlist: [], states: [], pattern_alerts: [] },
  pool_size: 0,
  thresholds: { oi_usd_limit: 1_500_000, oi_pct_limit: 5 },
};
