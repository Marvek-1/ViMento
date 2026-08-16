// ============================================================================
// Server-Side Statistical Validity & Bybit Grid Research Dataset Engine
// ============================================================================

export type MarketRegime =
  | "TREND_UP"
  | "TREND_DOWN"
  | "RANGE_LOW_VOL"
  | "RANGE_HIGH_VOL"
  | "VOLATILITY_EXPANSION"
  | "VOLATILITY_CONTRACTION"
  | "HIGH_POSITIVE_FUNDING"
  | "HIGH_NEGATIVE_FUNDING";

export const ALL_MARKET_REGIMES: MarketRegime[] = [
  "TREND_UP",
  "TREND_DOWN",
  "RANGE_LOW_VOL",
  "RANGE_HIGH_VOL",
  "VOLATILITY_EXPANSION",
  "VOLATILITY_CONTRACTION",
  "HIGH_POSITIVE_FUNDING",
  "HIGH_NEGATIVE_FUNDING",
];

export interface GridResearchEventRow {
  timestamp: number;
  symbol: string;
  interval: string;

  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;

  mark_price: number;
  index_price: number;
  funding_rate: number;
  next_funding_time: number;
  open_interest: number;

  best_bid: number;
  best_ask: number;
  spread_bps: number;

  realized_volatility: number;
  ATR: number;
  RSI: number;
  MA_fast: number;
  MA_slow: number;
  regime: MarketRegime;

  grid_lower: number;
  grid_upper: number;
  grid_count: number;
  grid_spacing: number;
  grid_type: "arithmetic" | "geometric";

  side: "BUY" | "SELL" | "LONG" | "SHORT";
  grid_index: number;
  entry_price: number;
  exit_price: number;
  quantity: number;
  notional: number;

  maker_fee: number;
  taker_fee: number;
  funding_paid_received: number; // Signed (+ received, - paid)
  slippage: number;
  gross_pnl: number;
  net_pnl: number; // gross_pnl - maker_fee - taker_fee - slippage + funding_paid_received

  margin_used: number;
  free_margin: number;
  leverage: number;
  liquidation_price: number;
  liquidation_distance_pct: number;

  reason_opened: string;
  reason_closed: string;
  duration_ms: number;
  strategy_version: string;
}

export interface RegimeExpectancy {
  regime: MarketRegime;
  count: number;
  percentOfTotal: number;
  meanNetBps: number;
  meanNetPnl: number;
  winRate: number;
  sampleStd: number;
  standardError: number;
  ciLower: number;
  ciUpper: number;
  grossPnlTotal: number;
  feesTotal: number;
  slippageTotal: number;
  fundingTotal: number;
  netPnlTotal: number;
}

export interface GridResearchDatasetSummary {
  dataset_id: string;
  symbol: string;
  interval: string;
  cycle_count: number;
  statistical_status: "insufficient" | "exploratory" | "evaluable" | "tuning-quality";
  status_explanation: string;
  date_range: {
    start: string;
    end: string;
  };
  overall_expectancy: {
    mean_bps: number;
    mean_pnl: number;
    sample_std: number;
    standard_error: number;
    ci_95_lower: number;
    ci_95_upper: number;
    t_stat: number;
  };
  accounting_summary: {
    gross_pnl: number;
    maker_fees: number;
    taker_fees: number;
    slippage: number;
    funding_received: number;
    funding_paid: number;
    net_pnl: number;
    net_bps: number;
  };
  regime_breakdown: Record<MarketRegime, RegimeExpectancy>;
  events_sample: GridResearchEventRow[];
}
