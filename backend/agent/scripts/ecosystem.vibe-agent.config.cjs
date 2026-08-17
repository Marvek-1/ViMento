// ecosystem.vibe-agent.config.cjs
// PM2 managed process for the Vibe agent API server.
//
// Start:   pm2 start  scripts/ecosystem.vibe-agent.config.cjs
// Status:  pm2 status
// Logs:    pm2 logs vibe-agent
// Persist: pm2 save

const path = require("path");

// scripts/ is __dirname; agent/ is one level up.
const agentDir = path.resolve(__dirname, "..");
const python   = path.resolve(agentDir, "../../.venv/bin/python");

module.exports = {
  apps: [
    {
      name: "vibe-agent",
      cwd: agentDir,
      script: python,
      interpreter: "none",
      args: [
        "api_server.py",
        "--host", "0.0.0.0",
        "--port", "8890",
      ],
      env: {
        // Hard safety guard: never start in live-trading mode via PM2.
        ENABLE_LIVE_TRADING: "false",
        LANGCHAIN_PROVIDER: "ollama",
        LANGCHAIN_MODEL_NAME: "vibe-qwen3-4b-64k:latest",
        OLLAMA_BASE_URL: "http://127.0.0.1:11434",
      },
      // Load .env from agent/ so all API keys are present.
      env_file: path.resolve(agentDir, ".env"),
      autorestart: true,
      restart_delay: 5000,
      exp_backoff_restart_delay: 100,
      max_restarts: 10,
      min_uptime: "30s",
      // Stream stdout/stderr to PM2 log files.
      out_file: "/tmp/vibe-agent.out.log",
      error_file: "/tmp/vibe-agent.err.log",
      merge_logs: true,
    },
  ],
};
