// ============================================================================
// Statistical Validity & Sample-Size Guards for Trading Strategies
// ============================================================================

export type TradeSampleStatus = "INSUFFICIENT" | "PRELIMINARY" | "EVALUABLE" | "STRONG_SAMPLE";
export type GridCycleStatus = "insufficient" | "exploratory" | "evaluable" | "tuning-quality";

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

export interface StatisticalStatusInfo {
  status: TradeSampleStatus;
  label: string;
  badgeClass: string;
  isSharpeValid: boolean;
  minRecommendedTrades: number;
  explanation: string;
}

export interface GridStatisticalStatusInfo {
  status: GridCycleStatus;
  label: string;
  badgeClass: string;
  isTuningReady: boolean;
  minRecommendedCycles: number;
  explanation: string;
}

/**
 * Standard trade-level statistical sample size evaluation
 * Rule:
 *   trades < 30   -> INSUFFICIENT (Sharpe ratio is unstable / artifact)
 *   trades < 100  -> PRELIMINARY
 *   trades < 300  -> EVALUABLE
 *   trades >= 300 -> STRONG_SAMPLE
 */
export function getTradeStatisticalStatus(trades: number | undefined | null): StatisticalStatusInfo {
  const count = typeof trades === "number" && Number.isFinite(trades) ? trades : 0;

  if (count < 30) {
    return {
      status: "INSUFFICIENT",
      label: "Insufficient",
      badgeClass: "bg-destructive/10 text-destructive border-destructive/30",
      isSharpeValid: false,
      minRecommendedTrades: 30,
      explanation: `Sample size (N=${count}) is below the minimum threshold (N=30). Reported Sharpe ratios are statistical artifacts and cannot be used for model selection.`,
    };
  }

  if (count < 100) {
    return {
      status: "PRELIMINARY",
      label: "Preliminary",
      badgeClass: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30",
      isSharpeValid: true,
      minRecommendedTrades: 100,
      explanation: `Preliminary sample (N=${count}). Adequate for hypothesis exploration but susceptible to small sample noise.`,
    };
  }

  if (count < 300) {
    return {
      status: "EVALUABLE",
      label: "Evaluable",
      badgeClass: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
      isSharpeValid: true,
      minRecommendedTrades: 300,
      explanation: `Evaluable sample size (N=${count}). Sufficient statistical power for initial model comparison.`,
    };
  }

  return {
    status: "STRONG_SAMPLE",
    label: "Strong Sample",
    badgeClass: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
    isSharpeValid: true,
    minRecommendedTrades: 300,
    explanation: `Strong sample size (N=${count} >= 300). High statistical confidence and narrow error bounds.`,
  };
}

/**
 * Grid-specific cycle statistical sample size evaluation
 * Rule:
 *   cycles < 50    -> insufficient
 *   cycles 50-199  -> exploratory
 *   cycles 200-499 -> evaluable (initial read)
 *   cycles >= 500  -> tuning-quality (aggressive parameter tuning)
 */
export function getGridStatisticalStatus(cycles: number | undefined | null): GridStatisticalStatusInfo {
  const count = typeof cycles === "number" && Number.isFinite(cycles) ? cycles : 0;

  if (count < 50) {
    return {
      status: "insufficient",
      label: "Insufficient",
      badgeClass: "bg-destructive/10 text-destructive border-destructive/30",
      isTuningReady: false,
      minRecommendedCycles: 50,
      explanation: `Insufficient completed grid cycles (N=${count} < 50). Minimum 200 cycles required for an initial read.`,
    };
  }

  if (count < 200) {
    return {
      status: "exploratory",
      label: "Exploratory",
      badgeClass: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30",
      isTuningReady: false,
      minRecommendedCycles: 200,
      explanation: `Exploratory grid sample (N=${count}). Can observe basic rung behavior, but not enough for statistical confidence.`,
    };
  }

  if (count < 500) {
    return {
      status: "evaluable",
      label: "Evaluable",
      badgeClass: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
      isTuningReady: true,
      minRecommendedCycles: 500,
      explanation: `Evaluable sample size (N=${count} >= 200). Meets the minimum benchmark for comparing grid configurations.`,
    };
  }

  return {
    status: "tuning-quality",
    label: "Tuning Quality",
    badgeClass: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
    isTuningReady: true,
    minRecommendedCycles: 500,
    explanation: `Tuning-quality sample (N=${count} >= 500). High statistical fidelity for tuning spacing, range %, and leverage.`,
  };
}

/**
 * Computes Expectancy E[R], Standard Error SE(R_bar), and 95% Confidence Interval
 * E[R] = (1/N) * sum(R_i)
 * s = sqrt( (1/(N-1)) * sum( (R_i - E[R])^2 ) )
 * SE(R_bar) = s / sqrt(N)
 * 95% CI = [E[R] - 1.96 * SE, E[R] + 1.96 * SE]
 */
export function computeExpectancyAndCI(returns: number[]): {
  count: number;
  mean: number;
  sampleStd: number;
  standardError: number;
  ciLower: number;
  ciUpper: number;
  tStat: number;
} {
  const n = returns.length;
  if (n === 0) {
    return {
      count: 0,
      mean: 0,
      sampleStd: 0,
      standardError: 0,
      ciLower: 0,
      ciUpper: 0,
      tStat: 0,
    };
  }

  const sum = returns.reduce((a, b) => a + b, 0);
  const mean = sum / n;

  if (n === 1) {
    return {
      count: 1,
      mean,
      sampleStd: 0,
      standardError: 0,
      ciLower: mean,
      ciUpper: mean,
      tStat: 0,
    };
  }

  const variance = returns.reduce((acc, val) => acc + Math.pow(val - mean, 2), 0) / (n - 1);
  const sampleStd = Math.sqrt(variance);
  const standardError = sampleStd / Math.sqrt(n);

  const z = 1.96; // 95% two-tailed normal approximation
  const ciLower = mean - z * standardError;
  const ciUpper = mean + z * standardError;
  const tStat = standardError > 0 ? mean / standardError : 0;

  return {
    count: n,
    mean,
    sampleStd,
    standardError,
    ciLower,
    ciUpper,
    tStat,
  };
}

/**
 * Complete Event-Level Grid Cycle Telemetry Row Schema (40+ Columns)
 */
export interface GridResearchEventRow {
  // Time & Symbol
  timestamp: number;
  symbol: string;
  interval: string;

  // Market & Orderbook Kline
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;

  // Mark & Derivatives
  mark_price: number;
  index_price: number;
  funding_rate: number;
  next_funding_time: number;
  open_interest: number;

  // Microstructure
  best_bid: number;
  best_ask: number;
  spread_bps: number;

  // Technical & Regime Indicators
  realized_volatility: number;
  ATR: number;
  RSI: number;
  MA_fast: number;
  MA_slow: number;
  regime: MarketRegime;

  // Grid Configuration
  grid_lower: number;
  grid_upper: number;
  grid_count: number;
  grid_spacing: number;
  grid_type: "arithmetic" | "geometric";

  // Cycle Execution
  side: "BUY" | "SELL" | "LONG" | "SHORT";
  grid_index: number;
  entry_price: number;
  exit_price: number;
  quantity: number;
  notional: number;

  // Strict Signed Accounting (bps & absolute USD)
  maker_fee: number;
  taker_fee: number;
  funding_paid_received: number; // Signed (+ received, - paid)
  slippage: number;
  gross_pnl: number;
  net_pnl: number; // gross_pnl - maker_fee - taker_fee - slippage + funding_paid_received

  // Margin & Risk
  margin_used: number;
  free_margin: number;
  leverage: number;
  liquidation_price: number;
  liquidation_distance_pct: number;

  // Lifecycle Metadata
  reason_opened: string;
  reason_closed: string;
  duration_ms: number;
  strategy_version: string;
}
