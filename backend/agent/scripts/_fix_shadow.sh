#!/bin/bash
# Kill all shadow paper session processes
ps -ef | grep 'shadow_ab_v1_control' | grep 'paper_session' | grep -v grep | awk '{print $2}' | xargs -r kill -9
sleep 2
# Verify killed
COUNT=$(ps -ef | grep 'shadow_ab_v1_control' | grep 'paper_session' | grep -v grep | wc -l)
echo "remaining shadow processes: $COUNT"

# Now fix session.json
cd /home/idona/MoStar/_apps/financial/Vibe-Trading-main/Vibe-Trading-main/agent
python3 -c "
import json
p = 'paper_sessions/shadow_ab_v1_control_20260711_185947/session.json'
with open(p) as f:
    d = json.load(f)
d.pop('accounting_status', None)
d.pop('accounting_error', None)
d.pop('accounting_error_detected_at', None)
with open(p, 'w') as f:
    json.dump(d, f, indent=2)
print('session.json cleaned')
"

# Clear pycache
rm -rf __pycache__

# Start the shadow session
nohup ../.venv/bin/python paper_session.py run --session-dir paper_sessions/shadow_ab_v1_control_20260711_185947 --poll-seconds 60 > /tmp/shadow_final2.log 2>&1 &
echo "PID=$!"
sleep 8
tail -5 /tmp/shadow_final2.log
