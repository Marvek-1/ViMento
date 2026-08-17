#!/bin/bash
echo "=== tmux sessions ==="
tmux list-sessions 2>&1 || true
echo "=== log tail ==="
test -f /tmp/vibe_agent.log && tail -60 /tmp/vibe_agent.log || echo "no log"
echo "=== /live/status ==="
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 3 http://127.0.0.1:8890/live_status 2>&1 || true
curl -s -o /dev/null -w "%{http_code}\n" --connect-timeout 3 http://127.0.0.1:8890/live/status 2>&1 || true
echo "=== /settings/llm ==="
curl -s --connect-timeout 3 http://127.0.0.1:8890/settings/llm 2>&1 || true
