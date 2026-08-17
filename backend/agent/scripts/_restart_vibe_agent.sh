#!/bin/bash
set -e
AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$AGENT_DIR"

# Ensure empty tool whitelist for Ollama 4B so AgentLoop can respond without 69 tool schemas
if ! grep -q '^VIBE_TRADING_ENABLED_TOOLS=' .env; then
    echo 'VIBE_TRADING_ENABLED_TOOLS=' >> .env
    echo "Added VIBE_TRADING_ENABLED_TOOLS= to .env"
fi

tmux kill-session -t vibe_agent 2>/dev/null || true

./_start_vibe_agent.sh vibe_agent 8890

echo "waiting for startup..."
sleep 12
curl -s -o /dev/null -w '%{http_code}\n' --connect-timeout 3 http://127.0.0.1:8890/live/status || true
curl -s --connect-timeout 3 http://127.0.0.1:8890/settings/llm | head -c 200 || true
echo
