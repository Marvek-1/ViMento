#!/bin/bash
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent
VENV=/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/.venv/bin/python
BASE=/home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent/paper_sessions
for s in v4_5m_control v4_5m_candidate v4_10m_control v4_10m_candidate v4_15m_control v4_15m_candidate; do
  $VENV paper_session.py run --session-dir $BASE/$s --poll-seconds 60 >> /tmp/${s}.log 2>&1 &
  echo "started $s pid=$!"
  sleep 1
done
wait
