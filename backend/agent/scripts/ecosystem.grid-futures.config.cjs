const path = require("path");

const agentDir = path.resolve(__dirname, "..");
const python = path.resolve(agentDir, "../../.venv/bin/python");
const runner = path.resolve(__dirname, "bounded_grid_runner.py");

// Separate ecosystem file from ecosystem.isolated-paper.config.cjs on
// purpose -- Grid Futures must be addable/removable without ever touching
// the six control_*/candidate_* PM2 app definitions.
const accounts = [
  ["grid_futures_5x", "b7e2b9d0-6b7a-4c4a-9c8b-1a2f3e4d5c6a", "bounded_grid_v1", 5],
  ["grid_futures_10x", "c8f3cae1-7c8b-4d5b-ad9c-2b3f4e5d6c7b", "bounded_grid_v1", 10],
];

module.exports = {
  apps: accounts.map(([worker, account, strategy, leverage]) => ({
    name: `vibe-${worker.replace(/_/g, "-")}`,
    cwd: agentDir,
    script: python,
    interpreter: "none",
    args: [
      runner,
      "--session-dir", path.resolve(agentDir, "paper_sessions", `${worker}_v3`),
      "--worker-id", worker,
      "--account-id", account,
      "--strategy-id", strategy,
      "--timeframe", "tick",
      "--mode", "paper",
      "--leverage", String(leverage),
      "--tick-seconds", "5",
    ],
    env: {
      ENABLE_LIVE_TRADING: "false",
      PAPER_BOOTSTRAP_TRADE_ENABLED: "false",
      VIBE_PAPER_DATABASE_URL: "dbname=idim_ikang port=5433",
    },
    autorestart: true,
    restart_delay: 5000,
    exp_backoff_restart_delay: 100,
    max_restarts: 10,
    min_uptime: "30s",
  })),
};
