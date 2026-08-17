import urllib.request
import json

try:
    req = urllib.request.Request("http://127.0.0.1:8787/snapshot")
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode())
    print("session_id:", d.get("session_id"))
    print("strategy:", d.get("strategy_type"))
    print("equity:", d.get("account", {}).get("current_equity"))
    print("open_positions:", len(d.get("account", {}).get("open_positions", [])))
except Exception as e:
    print("error:", e)
