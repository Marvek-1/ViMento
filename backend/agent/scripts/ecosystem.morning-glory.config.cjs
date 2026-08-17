const path = require("path");

const agentDir = path.resolve(__dirname, "..");
const python = path.resolve(agentDir, "../../.venv/bin/python");

module.exports = {
  apps: [{
    name: "vibe-morning-glory",
    cwd: agentDir,
    script: python,
    interpreter: "none",
    args: [
      path.resolve(__dirname, "morning_glory_runner.py"),
      "--session-dir", path.resolve(agentDir, "paper_sessions", "morning_glory_futures"),
      "--worker-id", "morning_glory",
      "--account-id", "da4f02c8-b49e-4c87-a3bc-9399b78f60a1",
      "--strategy-id", "funding_rate_zscore",
      "--timeframe", "tick",
      "--mode", "paper",
      "--leverage", "5",
      "--poll-seconds", "60",
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
  }],
};
