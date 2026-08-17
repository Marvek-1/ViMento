import urllib.request
import json

for sid in ["shadow_ab_v1_control_20260711_185947", "funding_live", "v4_5m_control"]:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:8787/api/status?session={sid}")
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode())
        print(f"{sid}: equity={d['account']['current_equity']} positions={len(d['account']['open_positions'])}")
    except Exception as e:
        print(f"{sid}: error={e}")
