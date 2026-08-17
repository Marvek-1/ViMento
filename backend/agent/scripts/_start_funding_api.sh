#!/bin/bash
tmux kill-session -t funding_api 2>/dev/null || true
sleep 1
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent
tmux new-session -d -s funding_api '../.venv/bin/python paper_dashboard_api.py --session-dir paper_sessions/funding_live --host 127.0.0.1 --port 8788'
sleep 3
echo "=== PANE ==="
tmux capture-pane -t funding_api -p
echo "=== HEALTH 8788 ==="
curl -s http://127.0.0.1:8788/health || true
echo
echo "=== STATUS 8788 ==="
curl -s http://127.0.0.1:8788/api/status | python3 -c "import sys,json; d=json.load(sys.stdin); print('equity:', d['account']['current_equity']); print('session:', d['session_id'])" 2>&1 || true
