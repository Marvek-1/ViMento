#!/bin/bash
set -e
AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$AGENT_DIR"

echo "Killing old paper_dashboard_api.py..."
pkill -f paper_dashboard_api.py 2>/dev/null || true
sleep 2
tmux kill-session -t dashproxy 2>/dev/null || true

echo "Starting dashproxy on port 8787..."
tmux new-session -d -s dashproxy \
    "cd '$AGENT_DIR' && ../.venv/bin/python paper_dashboard_api.py --session-dir paper_sessions/funding_live --host 0.0.0.0 --port 8787 >> /tmp/dashproxy.log 2>&1"

echo "Waiting for API..."
sleep 6
curl -s --connect-timeout 5 http://127.0.0.1:8787/api/portfolio | ../.venv/bin/python -c 'import sys,json; d=json.load(sys.stdin); a=d.get("account",{}); print("wallet:", a.get("wallet_balance"), "equity:", a.get("current_equity"))' || true
echo
tmux list-sessions
