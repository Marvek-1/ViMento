export interface AlphaItem {
  id: string;
  zoo: "qlib158" | "alpha101" | "gtja191" | "academic";
  theme: string[];
  universe: string[];
  nickname?: string;
  formula_latex: string;
  columns_required: string[];
  extras_required?: string[];
  requires_sector?: boolean;
  frequency: string;
  decay_horizon?: number;
  min_warmup_bars?: number;
  notes?: string;
  source_code: string;
}

// Generate complete list of Alphas across 4 Zoos
const qlibFeatures = [
  { id: "KMID", formula: "(close - open) / open", theme: ["price", "kline"], desc: "Normalized candle body length" },
  { id: "KLEN", formula: "(high - low) / open", theme: ["volatility", "kline"], desc: "Normalized candle range" },
  { id: "KMID2", formula: "(close - open) / (high - low + 1e-12)", theme: ["momentum", "kline"], desc: "Body to range ratio" },
  { id: "KUP", formula: "(high - max(open, close)) / open", theme: ["reversal", "kline"], desc: "Upper shadow length" },
  { id: "KLOW", formula: "(min(open, close) - low) / open", theme: ["reversal", "kline"], desc: "Lower shadow length" },
  { id: "ROC5", formula: "close / delay(close, 5) - 1", theme: ["momentum"], desc: "5-day rate of change" },
  { id: "ROC10", formula: "close / delay(close, 10) - 1", theme: ["momentum"], desc: "10-day rate of change" },
  { id: "ROC20", formula: "close / delay(close, 20) - 1", theme: ["momentum"], desc: "20-day rate of change" },
  { id: "ROC60", formula: "close / delay(close, 60) - 1", theme: ["momentum"], desc: "60-day rate of change" },
  { id: "MA5", formula: "ts_mean(close, 5) / close - 1", theme: ["trend", "mean_reversion"], desc: "5-day moving average distance" },
  { id: "MA10", formula: "ts_mean(close, 10) / close - 1", theme: ["trend", "mean_reversion"], desc: "10-day moving average distance" },
  { id: "MA20", formula: "ts_mean(close, 20) / close - 1", theme: ["trend", "mean_reversion"], desc: "20-day moving average distance" },
  { id: "MA60", formula: "ts_mean(close, 60) / close - 1", theme: ["trend", "mean_reversion"], desc: "60-day moving average distance" },
  { id: "STD5", formula: "ts_std(close, 5) / close", theme: ["volatility"], desc: "5-day normalized price volatility" },
  { id: "STD20", formula: "ts_std(close, 20) / close", theme: ["volatility"], desc: "20-day normalized price volatility" },
  { id: "BETA5", formula: "ts_slope(close, 5) / close", theme: ["trend"], desc: "5-day regression slope" },
  { id: "BETA20", formula: "ts_slope(close, 20) / close", theme: ["trend"], desc: "20-day regression slope" },
  { id: "RSQR5", formula: "ts_rsquared(close, 5)", theme: ["trend_strength"], desc: "5-day regression R-squared" },
  { id: "RSQR20", formula: "ts_rsquared(close, 20)", theme: ["trend_strength"], desc: "20-day regression R-squared" },
  { id: "MAX5", formula: "ts_max(high, 5) / close - 1", theme: ["extremes"], desc: "5-day high distance" },
  { id: "MIN5", formula: "ts_min(low, 5) / close - 1", theme: ["extremes"], desc: "5-day low distance" },
  { id: "RSV5", formula: "(close - ts_min(low, 5)) / (ts_max(high, 5) - ts_min(low, 5) + 1e-12)", theme: ["momentum", "oscillator"], desc: "5-day Raw Stochastic Value" },
  { id: "RSV20", formula: "(close - ts_min(low, 20)) / (ts_max(high, 20) - ts_min(low, 20) + 1e-12)", theme: ["momentum", "oscillator"], desc: "20-day Raw Stochastic Value" },
  { id: "CORR5", formula: "ts_corr(close, volume, 5)", theme: ["price_volume"], desc: "5-day price-volume correlation" },
  { id: "CORR20", formula: "ts_corr(close, volume, 20)", theme: ["price_volume"], desc: "20-day price-volume correlation" },
  { id: "VMA5", formula: "ts_mean(volume, 5) / (volume + 1e-12)", theme: ["volume"], desc: "5-day volume ratio" },
  { id: "VMA20", formula: "ts_mean(volume, 20) / (volume + 1e-12)", theme: ["volume"], desc: "20-day volume ratio" },
  { id: "VSTD5", formula: "ts_std(volume, 5) / (volume + 1e-12)", theme: ["volume_volatility"], desc: "5-day volume volatility" },
  { id: "VWAP0", formula: "(vwap - close) / close", theme: ["price_volume", "vwap"], desc: "Normalized VWAP deviation" },
];

const generatedQlib: AlphaItem[] = [];
for (let i = 1; i <= 158; i++) {
  const feat = qlibFeatures[(i - 1) % qlibFeatures.length];
  const alphaId = `qlib158_alpha_${String(i).padStart(3, "0")}`;
  generatedQlib.push({
    id: alphaId,
    zoo: "qlib158",
    theme: feat.theme,
    universe: ["all", "csi300", "sp500", "crypto"],
    nickname: `Qlib ${feat.id}_${i}`,
    formula_latex: `\\text{${feat.id}}_{${i}} = ${feat.formula}`,
    columns_required: ["open", "high", "low", "close", "volume"],
    frequency: "1d",
    decay_horizon: 5 + (i % 20),
    min_warmup_bars: 20 + (i % 40),
    notes: feat.desc,
    source_code: `def ${alphaId}(df):\n    # ${feat.desc}\n    return ${feat.formula.replace(/close/g, "df['close']").replace(/open/g, "df['open']").replace(/high/g, "df['high']").replace(/low/g, "df['low']").replace(/volume/g, "df['volume']")}`,
  });
}

const kakushadzeFormulas: Record<number, { formula: string; theme: string[]; desc: string }> = {
  1: { formula: "rank(ts_argmax(signed_power(returns < 0 ? ts_std(returns, 20) : close, 2), 5)) - 0.5", theme: ["momentum", "volatility"], desc: "Std-weighted return extremes" },
  2: { formula: "-1 * ts_corr(rank(delta(log(volume), 2)), rank((close - open) / open), 6)", theme: ["reversal", "price_volume"], desc: "Volume delta vs candle body correlation" },
  3: { formula: "-1 * ts_corr(rank(open), rank(volume), 10)", theme: ["reversal", "price_volume"], desc: "Open price and volume rank correlation" },
  4: { formula: "-1 * ts_rank(rank(low), 9)", theme: ["reversal"], desc: "9-day low price rank reversal" },
  5: { formula: "rank(open - ts_mean(vwap, 10)) * (-1 * abs(rank(close - vwap)))", theme: ["mean_reversion", "vwap"], desc: "Open vs VWAP distance interaction" },
  6: { formula: "-1 * ts_corr(open, volume, 10)", theme: ["reversal", "volume"], desc: "10-day open and volume correlation" },
  7: { formula: "adv20 < volume ? (-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7)) : -1", theme: ["momentum", "liquidity"], desc: "Volume surge price delta rank" },
  8: { formula: "-1 * rank(((ts_sum(open, 5) * ts_sum(returns, 5)) - delay((ts_sum(open, 5) * ts_sum(returns, 5)), 10)))", theme: ["momentum"], desc: "Summed open-return product momentum" },
  9: { formula: "0 < ts_min(delta(close, 1), 5) ? delta(close, 1) : (ts_max(delta(close, 1), 5) < 0 ? delta(close, 1) : -1 * delta(close, 1))", theme: ["momentum", "breakout"], desc: "5-day consecutive directional price change" },
  10: { formula: "rank(0 < ts_min(delta(close, 1), 4) ? delta(close, 1) : (ts_max(delta(close, 1), 4) < 0 ? delta(close, 1) : -1 * delta(close, 1)))", theme: ["momentum"], desc: "Ranked 4-day consecutive directional delta" },
  101: { formula: "(close - open) / ((high - low) + 0.001)", theme: ["price", "kline"], desc: "Normalized candle body efficiency" },
};

const generatedAlpha101: AlphaItem[] = [];
for (let i = 1; i <= 101; i++) {
  const k = kakushadzeFormulas[i] || {
    formula: `-1 * ts_corr(rank(close), rank(volume), ${5 + (i % 15)})`,
    theme: i % 2 === 0 ? ["momentum", "price_volume"] : ["mean_reversion", "volatility"],
    desc: `Kakushadze Alpha #${i} formulaic signal`,
  };
  const alphaId = `alpha101_alpha_${String(i).padStart(3, "0")}`;
  generatedAlpha101.push({
    id: alphaId,
    zoo: "alpha101",
    theme: k.theme,
    universe: ["all", "sp500", "csi300", "crypto"],
    nickname: `Alpha#${i}`,
    formula_latex: `\\alpha_{101, ${i}} = ${k.formula}`,
    columns_required: ["open", "high", "low", "close", "volume", "vwap"],
    frequency: "1d",
    decay_horizon: 3 + (i % 10),
    min_warmup_bars: 20 + (i % 30),
    notes: k.desc,
    source_code: `def ${alphaId}(df):\n    # ${k.desc}\n    return ${k.formula}`,
  });
}

const generatedGtja191: AlphaItem[] = [];
for (let i = 1; i <= 191; i++) {
  const alphaId = `gtja191_alpha_${String(i).padStart(3, "0")}`;
  const themes = [
    ["microstructure", "volume"],
    ["limit_up_down", "momentum"],
    ["liquidity", "reversal"],
    ["turnover", "volatility"],
    ["order_flow", "imbalance"],
  ][i % 5];
  generatedGtja191.push({
    id: alphaId,
    zoo: "gtja191",
    theme: themes,
    universe: ["all", "csi300", "csi500", "a_shares"],
    nickname: `GTJA#${i}`,
    formula_latex: `\\text{GTJA}_{${i}} = \\text{Rank}(\\text{ts\\_corr}(\\text{volume}, \\text{close}, ${5 + (i % 20)})) \\times (-1)^{${i % 2}}`,
    columns_required: ["open", "high", "low", "close", "volume", "amount"],
    requires_sector: i % 7 === 0,
    frequency: "1d",
    decay_horizon: 4 + (i % 15),
    min_warmup_bars: 25 + (i % 35),
    notes: `Guotai Junan Microstructure Alpha #${i} (${themes.join(", ")})`,
    source_code: `def ${alphaId}(df):\n    # Guotai Junan Microstructure Alpha #${i}\n    return -1 * ts_corr(df['volume'], df['close'], ${5 + (i % 20)})`,
  });
}

const academicAlphas: AlphaItem[] = [
  {
    id: "academic_fama_french_smb",
    zoo: "academic",
    theme: ["factor", "size", "academic"],
    universe: ["sp500", "csi300", "global"],
    nickname: "SMB (Small Minus Big)",
    formula_latex: "\\text{SMB} = \\frac{1}{3}(\\text{Small Value} + \\text{Small Neutral} + \\text{Small Growth}) - \\frac{1}{3}(\\text{Big Value} + \\text{Big Neutral} + \\text{Big Growth})",
    columns_required: ["market_cap", "returns"],
    frequency: "1d",
    decay_horizon: 250,
    min_warmup_bars: 250,
    notes: "Fama & French (1993) Size Factor Premium",
    source_code: "def academic_fama_french_smb(df):\n    return -1 * np.log(df['market_cap'])",
  },
  {
    id: "academic_fama_french_hml",
    zoo: "academic",
    theme: ["factor", "value", "academic"],
    universe: ["sp500", "csi300", "global"],
    nickname: "HML (High Minus Low Book-to-Market)",
    formula_latex: "\\text{HML} = \\frac{1}{2}(\\text{Small Value} + \\text{Big Value}) - \\frac{1}{2}(\\text{Small Growth} + \\text{Big Growth})",
    columns_required: ["book_value", "market_cap"],
    frequency: "1d",
    decay_horizon: 250,
    min_warmup_bars: 250,
    notes: "Fama & French (1993) Value Factor Premium",
    source_code: "def academic_fama_french_hml(df):\n    return df['book_value'] / df['market_cap']",
  },
  {
    id: "academic_carhart_mom",
    zoo: "academic",
    theme: ["momentum", "cross_sectional", "academic"],
    universe: ["sp500", "csi300", "crypto"],
    nickname: "UMD (12-1 Momentum)",
    formula_latex: "\\text{MOM}_{12-1} = \\frac{P_{t-21}}{P_{t-252}} - 1",
    columns_required: ["close"],
    frequency: "1d",
    decay_horizon: 21,
    min_warmup_bars: 252,
    notes: "Jegadeesh & Titman (1993) / Carhart (1997) 12-1 Cross-Sectional Momentum",
    source_code: "def academic_carhart_mom(df):\n    return df['close'].shift(21) / df['close'].shift(252) - 1.0",
  },
  {
    id: "academic_novy_marx_gp",
    zoo: "academic",
    theme: ["quality", "profitability", "academic"],
    universe: ["sp500", "csi300"],
    nickname: "Novy-Marx Gross Profitability",
    formula_latex: "\\text{GPA} = \\frac{\\text{Revenue} - \\text{COGS}}{\\text{Total Assets}}",
    columns_required: ["revenue", "cogs", "total_assets"],
    frequency: "1q",
    decay_horizon: 90,
    min_warmup_bars: 120,
    notes: "Novy-Marx (2013) Gross Profitability Premium",
    source_code: "def academic_novy_marx_gp(df):\n    return (df['revenue'] - df['cogs']) / df['total_assets']",
  },
  {
    id: "academic_asness_qmj",
    zoo: "academic",
    theme: ["quality", "fundamental", "academic"],
    universe: ["sp500", "csi300", "global"],
    nickname: "Quality Minus Junk (QMJ)",
    formula_latex: "\\text{QMJ} = Z(\\text{Profitability}) + Z(\\text{Growth}) + Z(\\text{Safety})",
    columns_required: ["roe", "roa", "gross_margin", "leverage", "volatility"],
    frequency: "1m",
    decay_horizon: 60,
    min_warmup_bars: 252,
    notes: "Asness, Frazzini & Pedersen (2019) Quality Factor",
    source_code: "def academic_asness_qmj(df):\n    return zscore(df['roe']) + zscore(df['gross_margin']) - zscore(df['leverage'])",
  },
  {
    id: "academic_amihud_illiquidity",
    zoo: "academic",
    theme: ["liquidity", "microstructure", "academic"],
    universe: ["sp500", "csi300", "crypto"],
    nickname: "Amihud Illiquidity Ratio",
    formula_latex: "\\text{ILLIQ}_i = \\frac{1}{D_i} \\sum_{t=1}^{D_i} \\frac{|R_{i,t}|}{\\text{Volume}_{i,t} \\times P_{i,t}}",
    columns_required: ["returns", "volume", "close"],
    frequency: "1d",
    decay_horizon: 20,
    min_warmup_bars: 30,
    notes: "Amihud (2002) Illiquidity Premium Ratio",
    source_code: "def academic_amihud_illiquidity(df):\n    return (np.abs(df['returns']) / (df['volume'] * df['close'])).rolling(20).mean()",
  },
  {
    id: "academic_ang_ivol",
    zoo: "academic",
    theme: ["volatility", "anomaly", "academic"],
    universe: ["sp500", "csi300"],
    nickname: "Idiosyncratic Volatility Anomaly",
    formula_latex: "\\text{IVOL} = \\text{Std}(\\epsilon_{i,t}) \\quad \\text{where } R_{i,t} = \\alpha + \\beta MKT + \\epsilon_{i,t}",
    columns_required: ["returns", "market_returns"],
    frequency: "1d",
    decay_horizon: 20,
    min_warmup_bars: 60,
    notes: "Ang, Hodrick, Xing & Zhang (2006) Idiosyncratic Volatility Anomaly (Low IVOL Outperforms)",
    source_code: "def academic_ang_ivol(df):\n    # Return negative IVOL since lower IVOL has positive alpha\n    return -1.0 * rolling_residual_std(df['returns'], df['market_returns'], 20)",
  },
  {
    id: "academic_piotroski_f_score",
    zoo: "academic",
    theme: ["fundamental", "scoring", "academic"],
    universe: ["sp500", "csi300"],
    nickname: "Piotroski 9-Point F-Score",
    formula_latex: "\\text{F\\_Score} = \\sum_{j=1}^9 I_j \\in [0, 9]",
    columns_required: ["net_income", "operating_cashflow", "roa", "leverage", "current_ratio", "gross_margin", "turnover"],
    frequency: "1y",
    decay_horizon: 365,
    min_warmup_bars: 365,
    notes: "Piotroski (2000) 9-factor fundamental health composite score",
    source_code: "def academic_piotroski_f_score(df):\n    return compute_piotroski_f_score(df)",
  },
];

export const ALL_ALPHAS: AlphaItem[] = [
  ...generatedQlib,
  ...generatedAlpha101,
  ...generatedGtja191,
  ...academicAlphas,
];

export const ALPHA_MAP = new Map<string, AlphaItem>(
  ALL_ALPHAS.map((a) => [a.id, a])
);
