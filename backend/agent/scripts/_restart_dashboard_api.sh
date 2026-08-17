#!/bin/bash
tmux kill-session -t dashboard_api 2>/dev/null || true
pkill -f "paper_dashboard_api.py.*--port 8787" 2>/dev/null || true
sleep 1
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent
tmux new-session -d -s dashboard_api '../.venv/bin/python paper_dashboard_api.py --session-dir paper_sessions/shadow_ab_v1_control_20260711_185947 --host 127.0.0.1 --port 8787'
sleep 3
echo "=== PANE ==="
tmux capture-pane -t dashboard_api -p
echo "=== HEALTH 8787 ==="
curl -s http://127.0.0.1:8787/health || true
echo
echo "=== SESSIONS 8787 ==="
curl -s http://127.0.0.1:8787/api/sessions || true
echo
echo "=== STATUS FUNDING ==="
curl -s 'http://127.0.0.1:8787/api/status?session=funding_live' | python3 -c "import sys,json; d=json.load(sys.stdin); print('equity:', d['account']['current_equity'])" 2>&1 || true
