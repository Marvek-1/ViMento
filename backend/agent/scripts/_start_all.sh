#!/bin/bash
set -e
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent

# Kill any existing processes
ps -ef | grep 'paper_session.py run' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null || true
ps -ef | grep 'paper_dashboard_api' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null || true
ps -ef | grep 'vite.*5899' | grep -v grep | awk '{print $2}' | xargs -r kill -9 2>/dev/null || true
sleep 1

# Clear pycache
rm -rf __pycache__

# Start paper session loops
for d in paper_sessions/v4_5m_control paper_sessions/v4_5m_candidate paper_sessions/v4_10m_control paper_sessions/v4_10m_candidate paper_sessions/v4_15m_control paper_sessions/v4_15m_candidate; do
  if [ -d "$d" ]; then
    nohup ../.venv/bin/python paper_session.py run --session-dir "$d" --poll-seconds 60 > "/tmp/$(basename $d).log" 2>&1 &
  fi
done
nohup ../.venv/bin/python paper_session.py run --session-dir paper_sessions/shadow_ab_v1_control_20260711_185947 --poll-seconds 60 > /tmp/shadow_session.log 2>&1 &

# Start dashboard API
nohup ../.venv/bin/python paper_dashboard_api.py --session-dir paper_sessions/shadow_ab_v1_control_20260711_185947 --host 127.0.0.1 --port 8787 > /tmp/dashboard_api.log 2>&1 &

# Start frontend
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/frontend
nohup ./node_modules/.bin/vite --host 0.0.0.0 --port 5899 > /tmp/vite_dev.log 2>&1 &

sleep 5
echo "=== PROCESSES ==="
ps -ef | grep -E 'paper_session|paper_dashboard_api|vite.*5899' | grep -v grep
echo "=== HEALTH ==="
curl -s --connect-timeout 3 http://127.0.0.1:8787/health 2>&1
echo
curl -s --connect-timeout 3 http://127.0.0.1:5899/ 2>&1 | head -1
