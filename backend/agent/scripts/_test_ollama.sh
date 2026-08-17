#!/bin/bash
echo "=== installed ollama models ==="
curl -s --connect-timeout 5 http://127.0.0.1:11434/api/tags | .venv/bin/python -c 'import sys,json; data=json.load(sys.stdin); print([m["name"] for m in data.get("models",[])])' 2>&1 || true
echo "=== generate vibe-qwen3-4b-64k:latest (30s max) ==="
curl -s --max-time 30 -X POST http://127.0.0.1:11434/api/generate -d '{"model":"vibe-qwen3-4b-64k:latest","prompt":"hi","stream":false}' -H "Content-Type: application/json" | head -c 200
echo
echo "=== generate qwen2.5:32b (60s max) ==="
curl -s --max-time 60 -X POST http://127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:32b","prompt":"hi","stream":false}' -H "Content-Type: application/json" | head -c 200
echo
