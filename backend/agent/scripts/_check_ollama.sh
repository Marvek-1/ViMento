#!/bin/bash
echo '--- ollama procs ---'
ps aux | grep -i ollama | grep -v grep || true
echo '--- 11434 /api/tags (10s timeout) ---'
curl -s --connect-timeout 10 http://127.0.0.1:11434/api/tags | head -c 300 || true
echo
echo '--- 11435 /api/tags (10s timeout) ---'
curl -s --connect-timeout 10 http://127.0.0.1:11435/api/tags | head -c 300 || true
echo
echo '--- /proc/net/tcp 11434(0x2C22) 11435(0x2C23) ---'
grep ':2C22' /proc/net/tcp || true
grep ':2C23' /proc/net/tcp || true
echo '--- ollama list 11434 ---'
OLLAMA_HOST=127.0.0.1:11434 /home/idona/.local/bin/ollama list 2>&1 | head -20 || true
echo '--- ollama list 11435 ---'
OLLAMA_HOST=127.0.0.1:11435 /home/idona/.local/bin/ollama list 2>&1 | head -20 || true
echo '--- find vibe-qwen3 model blobs ---'
find /usr/share/ollama ~/.ollama /root/.ollama -name '*vibe-qwen3*' 2>/dev/null | head -20 || true
