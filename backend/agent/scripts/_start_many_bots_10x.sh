#!/bin/bash
set -e
SESSION_DIR=paper_sessions/many_bots_10x
SYMBOLS=$(cat /tmp/symbols_109.txt)
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent

# Kill any existing many_bots_10x processes
tmux kill-session -t many_bots_10x 2>/dev/null || true
pkill -f "run.*many_bots_10x" 2>/dev/null || true
rm -rf "$SESSION_DIR" 2>/dev/null || true

# Start the session with 109 symbols, 10x leverage, $20 fixed margin
../.venv/bin/python paper_session.py start \
  --session-dir "$SESSION_DIR" \
  --symbols "$SYMBOLS" \
  --cash 25000 \
  --rebalance-hours 24 \
  --fee-rate 0.0005 \
  --leverage 10.0 \
  --margin-mode isolated \
  --fixed-margin 20 \
  --take-profit-pct 0.10 \
  --stop-loss-pct 0.05 \
  --trailing-stop-pct 0.03 \
  --max-hold-hours 48 \
  --min-notional 0.0

# Force initial rebalance to open all 109 positions immediately
../.venv/bin/python paper_session.py rebalance --session-dir "$SESSION_DIR" --force

# Start the loop in tmux
tmux new-session -d -s many_bots_10x '../.venv/bin/python paper_session.py run --session-dir paper_sessions/many_bots_10x --poll-seconds 60'
sleep 5
echo "=== PANE ==="
tmux capture-pane -t many_bots_10x -p
echo "=== MARKS ==="
tail -1 paper_sessions/many_bots_10x/marks.jsonl 2>/dev/null || echo "no marks yet"
