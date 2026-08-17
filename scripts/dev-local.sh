#!/usr/bin/env bash
# ============================================================================
# ViMento: bring the backend up locally, from a clean checkout
# ============================================================================
#
#   ./scripts/dev-local.sh              # set up if needed, then serve on :8010
#   ./scripts/dev-local.sh --port 9000  # different port
#   ./scripts/dev-local.sh --setup      # install deps and exit
#   ./scripts/dev-local.sh --stop       # stop a background instance
#
# Three things bite a fresh checkout; this script handles all of them:
#
#   1. `pip install -e .` FAILS with "error in 'egg_base' option: 'agent' does
#      not exist". pyproject.toml declares package-dir = {"" = "agent"} but the
#      tree is backend/agent/. We install backend/agent/requirements.txt
#      directly and put backend/agent on sys.path instead.
#   2. `cli/_version.py` is imported by api_server.py but has gone missing from
#      the repo before. If it is absent, pull it back: ./scripts/sync-vps.sh pull
#   3. The UI is resolved as __file__/../../frontend/dist. Docker flattens
#      agent/ to /app/agent so that lands on /app/frontend; on a checkout it
#      lands on backend/frontend, which must be a symlink to ../frontend.
# ============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${REPO_DIR}/.venv"
PY="${VENV}/bin/python"
AGENT_DIR="${REPO_DIR}/backend/agent"
LOG="${REPO_DIR}/.dev-local.log"
PORT=8010
MODE=serve

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

die() { echo -e "${RED}error:${NC} $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --port)  PORT="$2"; shift 2 ;;
    --setup) MODE=setup; shift ;;
    --stop)  MODE=stop;  shift ;;
    *) die "unknown flag '$1'" ;;
  esac
done

# Self-excluding bracket pattern, so pkill cannot match its own command line.
PATTERN="[a]pi_server[.]py"

if [ "${MODE}" = stop ]; then
  pkill -f "${PATTERN}" 2>/dev/null && echo -e "${GREEN}stopped${NC}" || echo "nothing running"
  exit 0
fi

# ── Preconditions ───────────────────────────────────────────────────────────
[ -f "${AGENT_DIR}/api_server.py" ] || die "missing backend/agent/api_server.py — wrong directory?"

if [ ! -f "${AGENT_DIR}/cli/_version.py" ]; then
  die "backend/agent/cli/_version.py is missing — api_server.py imports it and will crash.
  Restore the production tree with:  ./scripts/sync-vps.sh pull --yes"
fi

# ── Dependencies ────────────────────────────────────────────────────────────
if [ ! -x "${PY}" ]; then
  echo -e "${YELLOW}Creating virtualenv at .venv ...${NC}"
  python3 -m venv "${VENV}"
  "${PY}" -m pip install --upgrade pip -q
fi

if ! "${PY}" -c 'import fastapi, uvicorn' 2>/dev/null; then
  echo -e "${YELLOW}Installing backend requirements (several minutes, ~200 packages)...${NC}"
  "${PY}" -m pip install -r "${AGENT_DIR}/requirements.txt"
fi

# ── Frontend path shim ──────────────────────────────────────────────────────
if [ ! -e "${REPO_DIR}/backend/frontend" ]; then
  ln -sfn ../frontend "${REPO_DIR}/backend/frontend"
  echo -e "${BLUE}linked backend/frontend -> ../frontend (so the SPA resolves)${NC}"
fi
[ -f "${REPO_DIR}/frontend/dist/index.html" ] \
  || echo -e "${YELLOW}warn:${NC} no frontend/dist — the API will serve but / will 404. Build with: cd frontend && npm run build"

[ -f "${REPO_DIR}/.env" ] || [ -f "${AGENT_DIR}/.env" ] || cat <<EOF

${YELLOW}note:${NC} no .env found. The HTTP API and UI work without one, but preflight
      will report "LANGCHAIN_PROVIDER not set" and LLM-backed agent features
      stay disabled. See backend/agent/.env.example.
EOF

if [ "${MODE}" = setup ]; then
  echo -e "\n${GREEN}Setup complete.${NC} Start it with: ${BOLD}./scripts/dev-local.sh${NC}"
  exit 0
fi

# ── Serve ───────────────────────────────────────────────────────────────────
pkill -f "${PATTERN}" 2>/dev/null || true
sleep 2
rm -f "${LOG}"

cd "${AGENT_DIR}"   # sys.path[0] = backend/agent, so cli.* and src.* import
setsid nohup "${PY}" api_server.py --port "${PORT}" --host 127.0.0.1 \
  > "${LOG}" 2>&1 < /dev/null &

echo -e "${YELLOW}starting on :${PORT} ...${NC}"
for i in $(seq 1 90); do
  if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/health" 2>/dev/null; then
    echo -e "\n${GREEN}${BOLD}ViMento backend is up.${NC}"
    echo -e "  UI / API : ${BOLD}http://127.0.0.1:${PORT}${NC}"
    echo -e "  health   : $(curl -s "http://127.0.0.1:${PORT}/health" | head -c 120)"
    echo -e "  logs     : tail -f ${LOG}"
    echo -e "  stop     : ./scripts/dev-local.sh --stop"
    exit 0
  fi
  if ! pgrep -f "${PATTERN}" >/dev/null; then
    echo -e "${RED}server exited during startup:${NC}"; cat "${LOG}"; exit 1
  fi
  sleep 1
done

echo -e "${RED}timed out after 90s${NC}"; tail -30 "${LOG}"; exit 1
