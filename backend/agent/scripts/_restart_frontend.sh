#!/bin/bash
set -e

echo "Killing old uvicorn api_server:app on port 8000..."
pkill -f "uvicorn api_server:app --host 127.0.0.1 --port 8000" 2>/dev/null || true
sleep 2

echo "Starting api_server.py with frontend SPA on port 8000..."
tmux kill-session -t vibe 2>/dev/null || true
tmux new-session -d -s vibe "cd '/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent' && ../.venv/bin/python api_server.py --host 127.0.0.1 --port 8000 >> /tmp/vibe_api.log 2>&1"

echo "Waiting for startup..."
for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 http://127.0.0.1:8000/ 2>/dev/null || echo 000)
    if [ "$code" = "200" ]; then
        echo "Frontend is up on http://localhost:8000"
        curl -s http://127.0.0.1:8000/ | head -c 200
        echo
        exit 0
    fi
done
echo "Server did not respond in time; check /tmp/vibe_api.log"
tail -20 /tmp/vibe_api.log 2>/dev/null || true
exit 1
