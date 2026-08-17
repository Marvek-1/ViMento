const path = require("path");

const cwd = __dirname;
const python = path.resolve(cwd, "../../../.venv/bin/python");
const symbols = "BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT,XRP-USDT,ADA-USDT,DOGE-USDT,LINK-USDT";

function pairedApp(regimen, rebalanceHours) {
  return {
    name: `vibe-paper-${regimen}-paired`,
    cwd,
    script: python,
    interpreter: "none",
    args: [
      "shadow_ab_pair.py",
      "--control-dir", `paper_sessions/shadow_ab_v2_control_${regimen}`,
      "--candidate-dir", `paper_sessions/shadow_ab_v2_candidate10_${regimen}`,
      "--symbols", symbols,
      "--cash", "10000",
      "--rebalance-hours", String(rebalanceHours),
      "--fee-rate", "0.001",
      "--candidate-min-notional", "10",
      "--poll-seconds", "60",
    ],
    autorestart: true,
    restart_delay: 5000,
    max_restarts: 10,
    min_uptime: "30s",
  };
}

module.exports = {
  apps: [
    pairedApp("5m", 5 / 60),
    pairedApp("10m", 10 / 60),
    pairedApp("15m", 15 / 60),
  ],
};
