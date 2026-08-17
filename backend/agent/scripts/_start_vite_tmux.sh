#!/bin/bash
tmux kill-session -t vite5899 2>/dev/null || true
sleep 1
tmux new-session -d -s vite5899 -c /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/frontend './node_modules/.bin/vite --host 0.0.0.0 --port 5899'
sleep 4
echo "=== VITE TMUX SESSION ==="
tmux ls | grep vite5899
echo "=== PORT 5899 ==="
ss -ltn 2>/dev/null | grep 5899 || echo "not listening"
echo "=== HTTP ==="
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 3 http://127.0.0.1:5899/
