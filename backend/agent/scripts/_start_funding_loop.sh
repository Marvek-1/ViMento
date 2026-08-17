#!/bin/bash
tmux kill-session -t funding_live 2>/dev/null || true
sleep 1
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent
tmux new-session -d -s funding_live '../.venv/bin/python paper_session.py run-funding --session-dir paper_sessions/funding_live --poll-seconds 60'
sleep 5
echo "=== PANE ==="
tmux capture-pane -t funding_live -p
echo "=== MARKS ==="
ls -la paper_sessions/funding_live/marks.jsonl 2>/dev/null || echo "no marks file"
tail -1 paper_sessions/funding_live/marks.jsonl 2>/dev/null || echo "no marks yet"
