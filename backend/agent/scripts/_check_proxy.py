import urllib.request
import json

try:
    req = urllib.request.Request("http://127.0.0.1:5899/api/status")
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode())
    print("api/status via proxy: OK")
    print("equity:", d["account"]["current_equity"])
    print("wallet:", d["account"]["wallet_balance"])
    print("positions:", len(d["account"]["open_positions"]))
    print("trades:", d["stats"]["total_trades"])
except Exception as e:
    print("error:", e)
