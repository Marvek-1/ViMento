#!/bin/bash
echo "=== tmux sessions ==="
tmux list-sessions
echo "=== listening ports ==="
ss -ltn | grep -E ':(8000|8787|8890|8899)\b' || true
echo "=== 8000 /live/status ==="
curl -s -o /dev/null -w '%{http_code}\n' --connect-timeout 3 http://127.0.0.1:8000/live/status
echo "=== 8787 /api/portfolio ==="
curl -s -o /dev/null -w '%{http_code}\n' --connect-timeout 3 http://127.0.0.1:8787/api/portfolio
echo "=== 8890 /live/status ==="
curl -s -o /dev/null -w '%{http_code}\n' --connect-timeout 3 http://127.0.0.1:8890/live/status
echo "=== 8899 /live/status ==="
curl -s -o /dev/null -w '%{http_code}\n' --connect-timeout 3 http://127.0.0.1:8899/live/status
echo "=== dashproxy log ==="
tail -30 /tmp/dashproxy.log 2>/dev/null || true
echo
echo "=== vibe_agent log ==="
tail -30 /tmp/vibe_agent.log 2>/dev/null || true
echo
