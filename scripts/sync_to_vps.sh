#!/usr/bin/env bash
# ============================================================================
# Vibe-Trading: VPS Build, Sync & Deployment Pipeline
# Usage:
#   ./scripts/sync_to_vps.sh <user@vps-ip> [remote-directory]
# Example:
#   ./scripts/sync_to_vps.sh root@192.168.1.100 /opt/vibe-trading
# ============================================================================

set -euo pipefail

TARGET_HOST="${1:-}"
REMOTE_DIR="${2:-/opt/vibe-trading}"
IMAGE_NAME="vibe-trading"
IMAGE_TAG="latest"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

if [ -z "$TARGET_HOST" ]; then
  echo -e "${RED}Error: VPS target host is required.${NC}"
  echo "Usage: $0 <user@vps-ip> [remote-directory]"
  echo "Example: $0 root@123.45.67.89 /opt/vibe-trading"
  exit 1
fi

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}🚀 Vibe-Trading Continuous VPS Deployment Pipeline${NC}"
echo -e "${CYAN}Target Host: ${GREEN}${TARGET_HOST}${NC}"
echo -e "${CYAN}Remote Directory: ${GREEN}${REMOTE_DIR}${NC}"
echo -e "${CYAN}======================================================${NC}\n"

# Step 1: Verify local environment
echo -e "${YELLOW}[1/5] Checking local environment & dependencies...${NC}"
command -v docker >/dev/null 2>&1 || { echo -e "${RED}Docker is not installed locally.${NC}"; exit 1; }
command -v ssh >/dev/null 2>&1 || { echo -e "${RED}SSH is not installed locally.${NC}"; exit 1; }

# Step 2: Build the production Docker image
echo -e "\n${YELLOW}[2/5] Building production Docker container image (${IMAGE_NAME}:${IMAGE_TAG})...${NC}"
docker build -f Dockerfile.prod -t "${IMAGE_NAME}:${IMAGE_TAG}" .
echo -e "${GREEN}✓ Production Docker image built successfully.${NC}"

# Step 3: Prepare remote VPS directory
echo -e "\n${YELLOW}[3/5] Initializing remote directory on VPS (${REMOTE_DIR})...${NC}"
ssh "$TARGET_HOST" "mkdir -p '${REMOTE_DIR}' '${REMOTE_DIR}/data' '${REMOTE_DIR}/logs'"

# Copy deployment compose file and env template if not already present
echo -e "Syncing compose configuration..."
scp docker-compose.prod.yml "${TARGET_HOST}:${REMOTE_DIR}/docker-compose.yml"

ssh "$TARGET_HOST" "if [ ! -f '${REMOTE_DIR}/.env' ]; then touch '${REMOTE_DIR}/.env'; fi"

# Step 4: Stream and load Docker image onto VPS
echo -e "\n${YELLOW}[4/5] Shipping compressed Docker image to VPS...${NC}"
echo "Saving, compressing, and loading image over SSH pipeline..."
docker save "${IMAGE_NAME}:${IMAGE_TAG}" | gzip -c | ssh "$TARGET_HOST" "gzip -dc | docker load"
echo -e "${GREEN}✓ Image successfully loaded into remote Docker daemon.${NC}"

# Step 5: Launch / Restart containers on VPS with 24/7 restart policy
echo -e "\n${YELLOW}[5/5] Launching containers on VPS...${NC}"
ssh "$TARGET_HOST" "cd '${REMOTE_DIR}' && docker compose down --remove-orphans 2>/dev/null || true && docker compose up -d"

echo -e "\n${CYAN}======================================================${NC}"
echo -e "${GREEN}🎉 Deployment Complete! Continuous trading service is LIVE!${NC}"
echo -e "${CYAN}Status check:${NC}"
ssh "$TARGET_HOST" "cd '${REMOTE_DIR}' && docker compose ps"
echo -e "\n${CYAN}To view live logs from the VPS:${NC}"
echo -e "  ssh ${TARGET_HOST} \"cd ${REMOTE_DIR} && docker compose logs -f vibe-trading\""
echo -e "${CYAN}======================================================${NC}"
