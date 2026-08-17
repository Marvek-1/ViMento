#!/bin/bash
set -e
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent
# Kill existing paper session runners (only python ones)
ps -ef | grep "paper_session.py run --session-dir" | grep -v grep | grep -v "bash -c" | awk '{print $2}' | xargs -r kill -9
sleep 1
# Start v4 pairs
for d in paper_sessions/v4_*; do
  nohup ../.venv/bin/python paper_session.py run --session-dir "$d" --poll-seconds 60 > "/tmp/$(basename "$d")_restart.log" 2>&1 &
done
# Start shadow control session that the dashboard uses
nohup ../.venv/bin/python paper_session.py run --session-dir "paper_sessions/shadow_ab_v1_control_20260711_185947" --poll-seconds 60 > "/tmp/shadow_ab_v1_control_20260711_185947_restart.log" 2>&1 &
sleep 3
ps -ef | grep "paper_session.py run --session-dir" | grep -v grep | grep -v "bash -c"
