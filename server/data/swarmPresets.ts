import fs from "fs";
import path from "path";
import yaml from "js-yaml";

export interface SwarmPreset {
  name: string;
  title: string;
  description: string;
  agent_count: number;
  variables: { name: string; description: string; required: boolean }[];
  agents?: Array<{
    name: string;
    role: string;
    description?: string;
    tools?: string[];
    skills?: string[];
  }>;
}

const FALLBACK_PRESETS: SwarmPreset[] = [
  {
    name: "investment_committee",
    title: "Investment Committee",
    description: "Multidisciplinary executive review panel: Macro, Fundamental, Quant, and Risk officers debating allocation.",
    agent_count: 4,
    variables: [
      { name: "target_asset", description: "Symbol or asset class (e.g. BTC-USDT, NVDA, CSI300)", required: true },
      { name: "horizon", description: "Investment horizon (e.g. 1M, 6M, 1Y)", required: false },
      { name: "risk_budget", description: "Risk tolerance profile (e.g. conservative, moderate, aggressive)", required: false },
    ],
  },
  {
    name: "quant_strategy_desk",
    title: "Quant Strategy Desk",
    description: "Signal research, statistical arbitrage, backtesting validation, and portfolio optimization team.",
    agent_count: 4,
    variables: [
      { name: "strategy_family", description: "Strategy style (e.g. momentum, mean_reversion, multi_factor)", required: true },
      { name: "universe", description: "Target asset universe (e.g. crypto_top50, sp500, csi300)", required: true },
      { name: "timeframe", description: "Bar timeframe (e.g. 5m, 15m, 1h, 1d)", required: false },
    ],
  },
  {
    name: "crypto_trading_desk",
    title: "Crypto Trading Desk",
    description: "Futures perpetuals, funding rate arbitrage, order book imbalance, and liquidity-seeking execution.",
    agent_count: 3,
    variables: [
      { name: "pair", description: "Crypto perpetual pair (e.g. BTC-USDT, ETH-USDT, SOL-USDT)", required: true },
      { name: "leverage", description: "Target leverage (e.g. 5x, 10x)", required: false },
    ],
  },
  {
    name: "risk_committee",
    title: "Risk Committee",
    description: "Stress testing, tail-risk VaR, drawdown limits, and circuit-breaker validation team.",
    agent_count: 3,
    variables: [
      { name: "portfolio", description: "Current portfolio holdings and allocations", required: true },
      { name: "stress_scenario", description: "Macro shock scenario (e.g. 2008_lehman, 2020_covid, 2022_crypto_liquidity)", required: false },
    ],
  },
  {
    name: "factor_research_committee",
    title: "Factor Research Committee",
    description: "Alpha factory: IC/IR decay profiling, cross-sectional ranking, collinearity pruning, and multi-factor models.",
    agent_count: 4,
    variables: [
      { name: "factor_family", description: "Factor zoo (e.g. qlib158, alpha101, gtja191, academic)", required: true },
      { name: "universe", description: "Test universe (e.g. csi300, sp500, crypto)", required: true },
    ],
  },
];

export function getSwarmPresets(): SwarmPreset[] {
  const presetsDir = path.resolve("./backend/agent/src/swarm/presets");
  if (fs.existsSync(presetsDir)) {
    try {
      const files = fs.readdirSync(presetsDir).filter((f) => f.endsWith(".yaml") || f.endsWith(".yml"));
      const loaded: SwarmPreset[] = [];
      for (const file of files) {
        try {
          const raw = fs.readFileSync(path.join(presetsDir, file), "utf-8");
          const parsed = yaml.load(raw) as any;
          if (parsed && typeof parsed === "object") {
            const name = file.replace(/\.(yaml|yml)$/, "");
            const agents = parsed.agents || [];
            loaded.push({
              name,
              title: parsed.title || parsed.name || name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
              description: parsed.description || `Specialized swarm team for ${name.replace(/_/g, " ")}.`,
              agent_count: Array.isArray(agents) ? agents.length : (parsed.agent_count || 3),
              variables: parsed.variables || [
                { name: "target_asset", description: "Target symbol or universe", required: true },
                { name: "timeframe", description: "Analysis horizon", required: false },
              ],
              agents,
            });
          }
        } catch {
          // ignore error and continue
        }
      }
      if (loaded.length > 0) return loaded;
    } catch {
      // fallback
    }
  }
  return FALLBACK_PRESETS;
}
