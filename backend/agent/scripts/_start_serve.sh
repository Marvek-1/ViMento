#!/bin/bash
tmux kill-session -t dashweb 2>/dev/null || true
tmux kill-session -t serve5899 2>/dev/null || true
sleep 1
tmux new-session -d -s serve5899 -c /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/frontend 'npx -y serve -s dist -l 5899 -L'
sleep 8
echo "=== PORT ==="
ss -ltn 2>/dev/null | grep 5899 || echo "not listening"
echo "=== HTTP root ==="
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 5 http://127.0.0.1:5899/ || true
echo "=== HTTP paper-trading ==="
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 5 http://127.0.0.1:5899/paper-trading || true
echo "=== API ==="
curl -s http://127.0.0.1:8787/health || true
