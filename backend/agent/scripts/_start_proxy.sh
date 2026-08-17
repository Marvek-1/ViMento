#!/bin/bash
tmux kill-session -t dashproxy 2>/dev/null || true
tmux kill-session -t serve5899 2>/dev/null || true
tmux kill-session -t dashweb 2>/dev/null || true
sleep 1
tmux new-session -d -s dashproxy "/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/.venv/bin/python /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent/_proxy_dashboard.py"
sleep 3
echo "=== PROXY PANE ==="
tmux capture-pane -t dashproxy -p
echo "=== PORT ==="
ss -ltn 2>/dev/null | grep 5899 || echo "not listening"
echo "=== API HEALTH ==="
curl -s http://127.0.0.1:8787/health || true
echo
echo "=== ROOT ==="
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 5 http://127.0.0.1:5899/
echo "=== PAPER-TRADING ==="
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 5 http://127.0.0.1:5899/paper-trading
echo "=== API VIA PROXY ==="
curl -s --connect-timeout 5 http://127.0.0.1:5899/api/status | python3 -c "import sys,json; d=json.load(sys.stdin); print('equity:', d['account']['current_equity'])" 2>&1 || true
