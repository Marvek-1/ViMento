import urllib.request, json

try:
    req = urllib.request.Request("http://127.0.0.1:8787/health")
    with urllib.request.urlopen(req, timeout=5) as r:
        print("api health:", json.loads(r.read().decode())["ok"])
except Exception as e:
    print("api error:", e)

for path in ["/", "/paper-trading"]:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:5899{path}")
        with urllib.request.urlopen(req, timeout=5) as r:
            print(f"web {path}:", r.status)
    except Exception as e:
        print(f"web {path} error:", e)
