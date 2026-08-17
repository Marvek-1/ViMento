import json, sys
p = sys.argv[1] if len(sys.argv) > 1 else "/tmp/status2.json"
d = json.load(open(p))
acc = d["account"]
print("engine:", d["engine_status"])
print("positions:", len(acc["open_positions"]))
print("wallet:", acc["wallet_balance"])
print("reserved:", acc["reserved_margin"])
print("available:", acc["available_balance"])
print("equity:", acc["current_equity"])
print("pnl%:", acc["pnl_pct"])
print("first:", acc["open_positions"][0] if acc["open_positions"] else None)
print("trades:", d["stats"]["total_trades"])
