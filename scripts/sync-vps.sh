#!/usr/bin/env bash
# ============================================================================
# ViMento: sync this repo against the production tree on the VPS
# ============================================================================
#
#   ./scripts/sync-vps.sh status        # what differs, changes nothing
#   ./scripts/sync-vps.sh pull          # VPS  -> local   (dry-run)
#   ./scripts/sync-vps.sh pull --yes    # VPS  -> local   (for real)
#   ./scripts/sync-vps.sh push          # local -> VPS    (dry-run)
#   ./scripts/sync-vps.sh push --yes    # local -> VPS    (for real, backs up first)
#
# Override the target with env vars:
#   VPS_HOST=root@31.97.180.251  VPS_PATH=/opt/vibe-trading
#
# Design notes (learned the hard way — please keep these):
#   * --delete is NEVER used. The two trees are not mirrors: the VPS has no
#     top-level server/, src/ or package.json, and the repo has no
#     backend/scripts/docker-compose.yml. Deleting either direction destroys
#     real work. Reconcile by hand, not with rsync.
#   * paper_sessions/ is ~700MB of runtime data and is always excluded.
#   * push is dry-run by default and snapshots the remote before writing.
# ============================================================================

set -euo pipefail

VPS_HOST="${VPS_HOST:-root@31.97.180.251}"
VPS_PATH="${VPS_PATH:-/opt/vibe-trading}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# Code only. Runtime state, caches and dependency trees stay put on both ends.
EXCLUDES=(
  --exclude '.git'
  --exclude '.venv'
  --exclude 'node_modules'
  --exclude '__pycache__'
  --exclude '*.pyc'
  --exclude '.pytest_cache'
  --exclude 'paper_sessions'
  --exclude 'runs'
  --exclude 'data'
  --exclude 'logs'
  --exclude '*.egg-info'
)

die() { echo -e "${RED}error:${NC} $*" >&2; exit 1; }

check_ssh() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 "${VPS_HOST}" true 2>/dev/null \
    || die "cannot reach ${VPS_HOST} over SSH.
  On Windows run this from WSL — the WSL ~/.ssh holds the key, the Windows one does not:
    wsl -d Ubuntu-24.04 -- bash -c 'cd ${REPO_DIR} && ./scripts/sync-vps.sh $*'"
}

banner() {
  echo -e "${CYAN}${BOLD}"
  echo "======================================================================"
  echo "  ViMento sync   ${VPS_HOST}:${VPS_PATH}"
  echo "======================================================================"
  echo -e "${NC}"
}

cmd_status() {
  echo -e "${YELLOW}Files the VPS would send to local (pull):${NC}"
  rsync -azn --itemize-changes "${EXCLUDES[@]}" -e ssh \
    "${VPS_HOST}:${VPS_PATH}/" "${REPO_DIR}/" | grep -E '^[<>]' | head -40 || true
  echo
  echo -e "${YELLOW}Files local would send to the VPS (push):${NC}"
  rsync -azn --itemize-changes "${EXCLUDES[@]}" -e ssh \
    "${REPO_DIR}/" "${VPS_HOST}:${VPS_PATH}/" | grep -E '^[<>]' | head -40 || true
  echo
  # --itemize-changes is required: plain `rsync -azn` prints nothing to count.
  # Lines starting with < (send) or > (receive) are the actual file transfers.
  echo -e "${BLUE}(totals)${NC}"
  printf '  pull: %s file(s) VPS -> local\n' \
    "$(rsync -azn --itemize-changes "${EXCLUDES[@]}" -e ssh "${VPS_HOST}:${VPS_PATH}/" "${REPO_DIR}/" | grep -cE '^[<>]' || true)"
  printf '  push: %s file(s) local -> VPS\n' \
    "$(rsync -azn --itemize-changes "${EXCLUDES[@]}" -e ssh "${REPO_DIR}/" "${VPS_HOST}:${VPS_PATH}/" | grep -cE '^[<>]' || true)"
}

cmd_pull() {
  local live="$1"
  if [ "${live}" != "yes" ]; then
    echo -e "${YELLOW}DRY RUN — nothing is written. Re-run with --yes to apply.${NC}\n"
    rsync -azn --info=stats2 "${EXCLUDES[@]}" -e ssh \
      "${VPS_HOST}:${VPS_PATH}/" "${REPO_DIR}/" | tail -12
    return
  fi

  echo -e "${BLUE}Tagging current state as 'pre-vps-sync' so this is undoable...${NC}"
  git -C "${REPO_DIR}" tag -f pre-vps-sync >/dev/null 2>&1 \
    && echo -e "  ${GREEN}git reset --hard pre-vps-sync${NC} reverts this pull" \
    || echo -e "  ${YELLOW}(not a git repo — no safety tag)${NC}"

  echo -e "\n${YELLOW}Pulling ${VPS_HOST}:${VPS_PATH} -> ${REPO_DIR}${NC}"
  rsync -az --info=stats2 "${EXCLUDES[@]}" -e ssh \
    "${VPS_HOST}:${VPS_PATH}/" "${REPO_DIR}/" | tail -10

  # api_server.py resolves the UI as __file__/../../frontend/dist. Docker
  # flattens agent/ to /app/agent so that lands on /app/frontend; on a checkout
  # it lands on backend/frontend, which only exists as this link.
  ln -sfn ../frontend "${REPO_DIR}/backend/frontend"

  echo -e "\n${GREEN}Pull complete.${NC}"
  echo -e "  Review with ${BOLD}git status${NC} — and commit from Windows git, not WSL:"
  echo -e "  the two disagree on core.autocrlf and WSL will invent a ~21k-line diff."
}

cmd_push() {
  local live="$1"
  if [ "${live}" != "yes" ]; then
    echo -e "${YELLOW}DRY RUN — nothing is written. Re-run with --yes to apply.${NC}\n"
    rsync -azn --info=stats2 "${EXCLUDES[@]}" -e ssh \
      "${REPO_DIR}/" "${VPS_HOST}:${VPS_PATH}/" | tail -12
    echo -e "\n${RED}${BOLD}Read this before pushing:${NC}"
    echo -e "  Pushing does NOT restart anything. The 13 paper-trading containers"
    echo -e "  keep running the image they were built from. To actually roll code out:"
    echo -e "    ssh ${VPS_HOST} 'cd ${VPS_PATH}/backend/scripts && docker compose up -d --build'"
    echo -e "  That restarts live trading agents. Know that before you run it."
    return
  fi

  local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
  echo -e "${BLUE}Snapshotting remote tree first...${NC}"
  ssh "${VPS_HOST}" "tar czf /root/vibe-trading-backup-${stamp}.tar.gz \
    --exclude=node_modules --exclude=paper_sessions --exclude=.git \
    -C ${VPS_PATH} . 2>/dev/null; ls -lh /root/vibe-trading-backup-${stamp}.tar.gz"

  echo -e "\n${YELLOW}Pushing ${REPO_DIR} -> ${VPS_HOST}:${VPS_PATH}${NC}"
  rsync -az --info=stats2 "${EXCLUDES[@]}" -e ssh \
    "${REPO_DIR}/" "${VPS_HOST}:${VPS_PATH}/" | tail -10

  echo -e "\n${GREEN}Push complete — code copied, nothing restarted.${NC}"
  echo -e "  Rollback:  ${BOLD}ssh ${VPS_HOST} 'tar xzf /root/vibe-trading-backup-${stamp}.tar.gz -C ${VPS_PATH}'${NC}"
  echo -e "  Roll out:  ${BOLD}ssh ${VPS_HOST} 'cd ${VPS_PATH}/backend/scripts && docker compose up -d --build'${NC}"
}

main() {
  local cmd="${1:-status}" live="no"
  [ "${2:-}" = "--yes" ] && live="yes"

  command -v rsync >/dev/null || die "rsync not installed (apt install rsync)"
  banner
  check_ssh

  case "${cmd}" in
    status) cmd_status ;;
    pull)   cmd_pull "${live}" ;;
    push)   cmd_push "${live}" ;;
    *)      die "unknown command '${cmd}' (expected: status | pull | push)" ;;
  esac
}

main "$@"
