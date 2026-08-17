#!/bin/bash
set -e
AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$AGENT_DIR"
DIAG="/tmp/vibe_diag.log"
TEST="/tmp/vibe_test.log"
rm -f "$DIAG" "$TEST"
touch "$DIAG"

# Show .venv python and api_server.py check
echo "=== which python ===" >> "$DIAG"
ls -l ../.venv/bin/python >> "$DIAG" 2>&1
echo "=== python version ===" >> "$DIAG"
../.venv/bin/python --version >> "$DIAG" 2>&1
echo "=== help ===" >> "$DIAG"
../.venv/bin/python api_server.py --help >> "$DIAG" 2>&1 || true

echo "=== startup 8s ===" >> "$DIAG"
set -a
source "$AGENT_DIR/.env"
set +a
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export LANGCHAIN_PROVIDER="ollama"
export LANGCHAIN_MODEL_NAME="vibe-qwen3-4b-64k:latest"
if command -v timeout >/dev/null 2>&1; then
    timeout 8 ../.venv/bin/python api_server.py --host 0.0.0.0 --port 8890 >> "$TEST" 2>&1 || true
else
    ../.venv/bin/python api_server.py --host 0.0.0.0 --port 8890 >> "$TEST" 2>&1 &
    PID=$!
    sleep 8
    kill $PID 2>/dev/null || true
fi

echo "=== test log ===" >> "$DIAG"
cat "$TEST" >> "$DIAG" 2>&1 || true
echo "=== curl ===" >> "$DIAG"
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 3 http://127.0.0.1:8890/live_status 2>&1 || true
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 3 http://127.0.0.1:8890/live/status 2>&1 || true

echo "=== tmux sessions ===" >> "$DIAG"
tmux list-sessions >> "$DIAG" 2>&1 || true

cat "$DIAG"
