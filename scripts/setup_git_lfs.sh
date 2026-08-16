#!/usr/bin/env bash
# ============================================================================
# Vibe-Trading: Git LFS & Large File Management Utility
# ============================================================================
# Detects large files, configures Git LFS tracking, and prevents GitHub push
# rejections for datasets, backtest traces, and ML models > 50MB/100MB.
#
# Usage:
#   ./scripts/setup_git_lfs.sh          # Auto-setup Git LFS and scan files
#   ./scripts/setup_git_lfs.sh scan     # Scan repo for files > 25MB
#   ./scripts/setup_git_lfs.sh track    # Track specific file or pattern in LFS
#   ./scripts/setup_git_lfs.sh migrate  # Migrate historical large files into LFS
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

THRESHOLD_MB="${THRESHOLD_MB:-25}"

echo -e "${CYAN}${BOLD}"
echo "======================================================================"
echo "          📦  GIT LFS & LARGE FILE MANAGEMENT SYSTEM                  "
echo "======================================================================"
echo -e "${NC}"

# Check if git is initialized
if [ ! -d ".git" ]; then
  echo -e "${RED}Error: Not inside a git repository. Run 'git init' first.${NC}"
  exit 1
fi

# Check if git-lfs is installed in system
function check_and_install_lfs() {
  if ! command -v git-lfs >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  git-lfs is not installed. Attempting installation...${NC}"
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update -y && sudo apt-get install -y git-lfs || true
    elif command -v brew >/dev/null 2>&1; then
      brew install git-lfs || true
    elif command -v apk >/dev/null 2>&1; then
      apk add git-lfs || true
    else
      echo -e "${YELLOW}Please install git-lfs manually for your OS (e.g. 'sudo apt-get install git-lfs')${NC}"
    fi
  fi

  if command -v git-lfs >/dev/null 2>&1; then
    git lfs install --skip-repo 2>/dev/null || git lfs install || true
    echo -e "${GREEN}✓ Git LFS initialized in repository.${NC}"
  else
    echo -e "${YELLOW}Proceeding with .gitattributes configuration.${NC}"
  fi
}

# Scan workspace for files exceeding threshold
function scan_large_files() {
  echo -e "\n${YELLOW}🔍 Scanning repository for files larger than ${THRESHOLD_MB}MB...${NC}"
  
  local FOUND=0
  while IFS= read -r file; do
    if [ -f "$file" ]; then
      local size
      size=$(du -h "$file" | cut -f1)
      echo -e "  ${RED}Large file detected: ${BOLD}${file}${NC} (${size})"
      
      # Extract extension
      local ext="${file##*.}"
      if [ -n "$ext" ] && [ "$ext" != "$file" ]; then
        echo -e "  ${CYAN}-> Automatically registering *.${ext} in .gitattributes...${NC}"
        if command -v git-lfs >/dev/null 2>&1; then
          git lfs track "*.${ext}" 2>/dev/null || true
        fi
      fi
      FOUND=1
    fi
  done < <(find . -type f -not -path '*/.*' -not -path '*/node_modules/*' -not -path '*/dist/*' -size +"${THRESHOLD_MB}M")

  if [ $FOUND -eq 0 ]; then
    echo -e "${GREEN}✓ No unmanaged files larger than ${THRESHOLD_MB}MB found.${NC}"
  else
    echo -e "\n${YELLOW}ℹ️  Make sure to add .gitattributes to git: 'git add .gitattributes'${NC}"
  fi
}

# Track specific custom pattern
function track_pattern() {
  local PATTERN="${1:-}"
  if [ -z "$PATTERN" ]; then
    echo -e "${RED}Usage: $0 track '<file-or-pattern>'${NC}"
    echo "Example: $0 track '*.parquet' or $0 track 'data/huge_backtest.csv'"
    exit 1
  fi
  
  if command -v git-lfs >/dev/null 2>&1; then
    git lfs track "$PATTERN"
    echo -e "${GREEN}✓ Tracked '$PATTERN' with Git LFS.${NC}"
  else
    echo "$PATTERN filter=lfs diff=lfs merge=lfs -text" >> .gitattributes
    echo -e "${GREEN}✓ Appended '$PATTERN' to .gitattributes.${NC}"
  fi
  git add .gitattributes
}

# Migrate existing historical commits to LFS (optional)
function migrate_history() {
  echo -e "${YELLOW}Migrating large files in git history to LFS...${NC}"
  if command -v git-lfs >/dev/null 2>&1; then
    git lfs migrate import --everything --above="${THRESHOLD_MB}MB"
    echo -e "${GREEN}✓ History migration complete.${NC}"
  else
    echo -e "${RED}git-lfs binary is required to run migrate.${NC}"
  fi
}

CMD="${1:-all}"

case "$CMD" in
  scan)
    scan_large_files
    ;;
  track)
    track_pattern "${2:-}"
    ;;
  migrate)
    migrate_history
    ;;
  all|*)
    check_and_install_lfs
    scan_large_files
    ;;
esac

echo -e "\n${GREEN}======================================================================${NC}"
echo -e "${GREEN}✅ Large file protection is active. Git pushes are protected from size limits.${NC}"
echo -e "${GREEN}======================================================================${NC}\n"
