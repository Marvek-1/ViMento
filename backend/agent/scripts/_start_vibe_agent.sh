#!/usr/bin/env bash
# _start_vibe_agent.sh -- Start the Vibe agent API in a dedicated tmux session.
#
# Usage: scripts/_start_vibe_agent.sh [SESSION_NAME] [PORT]
#   SESSION_NAME  tmux session name (default: vibe_agent)
#   PORT          API port          (default: 8890)
#
# FIX 2026-08-05: AGENT_DIR is the *parent* of this script directory (agent/),
# not scripts/ itself.  The .env and api_server.py both live in agent/, and the
# cli/ module is resolved relative to agent/.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

TMUX_NAME="${1:-vibe_agent}"
API_PORT="${2:-8890}"

if tmux has-session -t "${TMUX_NAME}" 2>/dev/null; then
    echo "[vibe_agent] session '${TMUX_NAME}' exists -- attach: tmux attach -t ${TMUX_NAME}" >&2
    exit 1
fi

ENV_FILE="${AGENT_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    echo "[vibe_agent] Missing env file: ${ENV_FILE}" >&2
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export LANGCHAIN_PROVIDER="${LANGCHAIN_PROVIDER:-ollama}"
export LANGCHAIN_MODEL_NAME="${LANGCHAIN_MODEL_NAME:-vibe-qwen3-4b-64k:latest}"

# Hard safety guard -- this script never starts the agent in live-trading mode.
# Live enablement requires an explicit, authenticated mandate commit via the
# operator surface.
export ENABLE_LIVE_TRADING="false"

# Pin the agent port; do not let an ambient .env PORT variable override it.
API_PORT="${2:-8890}"

VENV="${AGENT_DIR}/../.venv/bin/python"
if [[ ! -x "${VENV}" ]]; then
    echo "[vibe_agent] venv not found: ${VENV}" >&2
    exit 1
fi

LOG_FILE="/tmp/${TMUX_NAME}.log"
rm -f "${LOG_FILE}"

tmux new-session -d -s "${TMUX_NAME}" \
    "cd '${AGENT_DIR}' && '${VENV}' api_server.py --host 0.0.0.0 --port ${API_PORT} >> '${LOG_FILE}' 2>&1"

echo "[vibe_agent] Started '${TMUX_NAME}' on port ${API_PORT} (logs: ${LOG_FILE})"
