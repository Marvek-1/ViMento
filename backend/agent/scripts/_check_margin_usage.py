import urllib.request
import json

for port in (8787, 8788):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        h = d.get("health", {})
        print(f"port {port} session={d.get('session_id')} margin_usage_pct={h.get('margin_usage_pct')} score={h.get('score')}")
    except Exception as e:
        print(f"port {port} error: {e}")
