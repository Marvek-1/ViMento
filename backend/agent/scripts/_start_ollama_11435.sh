#!/bin/bash
set -e
tmux kill-session -t ollama 2>/dev/null || true
tmux new-session -d -s ollama 'OLLAMA_HOST=127.0.0.1:11435 /home/idona/.local/bin/ollama serve >> /tmp/ollama_11435.log 2>&1'
echo 'waiting for Ollama 11435...'
for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    if curl -s --connect-timeout 3 http://127.0.0.1:11435/api/tags >/dev/null 2>&1; then
        echo 'Ollama 11435 is up'
        exit 0
    fi
done
echo 'Ollama 11435 did not respond in time; see /tmp/ollama_11435.log'
exit 1
