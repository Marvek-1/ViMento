const path = require("path");

const agentDir = path.resolve(__dirname, "..");
const python = path.resolve(agentDir, "../../.venv/bin/python");
const runner = path.resolve(__dirname, "grid_futures_runner.py");

const accounts = [
  ["control_5m", "59961ec7-10d3-4284-aaac-2030b9de6cc1", "control", "5m", 5, 300],
  ["control_10m", "805a5633-81c5-40b6-bda8-eae4e42b414b", "control", "10m", 5, 600],
  ["control_15m", "ab23f2fe-368c-48ba-873d-9173da8ad489", "control", "15m", 5, 900],
  ["candidate_5m", "7673c15e-44fe-4520-b866-3f1d88e2a4be", "candidate", "5m", 10, 300],
  ["candidate_10m", "6ff5c12f-d48d-4f8b-bd79-ae4aa75eee7f", "candidate", "10m", 10, 600],
  ["candidate_15m", "f1e4fca1-b329-46fc-8b04-a25683b6abcf", "candidate", "15m", 10, 900],
];

module.exports = {
  apps: accounts.map(([worker, account, strategy, timeframe, leverage, poll]) => ({
    name: `vibe-${worker}`,
    cwd: agentDir,
    script: python,
    interpreter: "none",
    args: [
      runner,
      "--session-dir", path.resolve(agentDir, "paper_sessions", `${worker}_futures`),
      "--worker-id", worker,
      "--account-id", account,
      "--strategy-id", strategy,
      "--timeframe", timeframe,
      "--mode", "paper",
      "--leverage", String(leverage),
      "--poll-seconds", String(poll),
    ],
    env: {
      ENABLE_LIVE_TRADING: "false",
      VIBE_PAPER_DATABASE_URL: "dbname=idim_ikang port=5433",
    },
    autorestart: true,
    restart_delay: 10000,
    exp_backoff_restart_delay: 100,
    max_restarts: 10,
    min_uptime: "60s",
  })),
};
