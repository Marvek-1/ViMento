import json
from futures_paper_engine import request_json

tickers = request_json("/fapi/v1/ticker/price")
symbols = [t["symbol"] for t in tickers if isinstance(t, dict) and t.get("symbol", "").endswith("USDT") and "_" not in t["symbol"]]
# normalize to BTC-USDT style
normalized = []
for s in symbols:
    base = s[:-4]
    normalized.append(f"{base}-USDT")
print(f"found {len(normalized)} USDT-M symbols")
with open("/tmp/symbols_109.txt", "w") as f:
    f.write(",".join(normalized[:109]))
print("wrote", min(len(normalized), 109), "symbols to /tmp/symbols_109.txt")
