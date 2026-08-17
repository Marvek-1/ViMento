import urllib.request
import json

req = urllib.request.Request("http://127.0.0.1:8787/api/status?session=many_bots_10x")
with urllib.request.urlopen(req, timeout=15) as r:
    d = json.loads(r.read().decode())

positions = d.get("account", {}).get("open_positions", [])
print("session:", d.get("session_id"))
print("positions:", len(positions))
if positions:
    print("leverage sample:", positions[1]["leverage"])
    print("margin sample:", positions[1]["margin"])
    print("notional sample:", positions[1]["notional"])
print("equity:", d.get("account", {}).get("current_equity"))
print("reserved:", d.get("account", {}).get("reserved_margin"))
