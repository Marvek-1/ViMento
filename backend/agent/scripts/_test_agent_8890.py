import json, time, urllib.request

base = "http://127.0.0.1:8890"

# create session
req = urllib.request.Request(
    f"{base}/sessions",
    data=json.dumps({"title": "agent-test-8890"}).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)
resp = urllib.request.urlopen(req, timeout=15)
sid = json.loads(resp.read().decode())["session_id"]
print(f"session_id: {sid}")

# send message
req2 = urllib.request.Request(
    f"{base}/sessions/{sid}/messages",
    data=json.dumps({"content": "hello"}).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)
resp2 = urllib.request.urlopen(req2, timeout=15)
print(f"send_message_status: {resp2.status}")
print(f"send_message_body: {resp2.read().decode()[:200]}")

# poll for assistant reply
for i in range(30):
    time.sleep(5)
    req3 = urllib.request.Request(f"{base}/sessions/{sid}/messages", method="GET")
    resp3 = urllib.request.urlopen(req3, timeout=15)
    msgs = json.loads(resp3.read().decode())
    assistant = [m for m in msgs if m.get("role") == "assistant"]
    print(f"poll {i+1} total={len(msgs)} assistant={len(assistant)}")
    if assistant:
        for m in assistant:
            content = m.get("content", "") or ""
            print(f"  assistant ({len(content)} chars): {content[:300]!r}")
        break
else:
    print("No assistant response within 150 seconds")
