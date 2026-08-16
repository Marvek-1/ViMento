#!/usr/bin/env bash
# ============================================================================
# Vibe-Trading: Production Docker Build & Deployment Automation
# ============================================================================
#
# Usage:
#   ./deploy.sh                  # Build image and run locally with Docker
#   ./deploy.sh compose          # Deploy full stack with Postgres & Nginx via Docker Compose
#   ./deploy.sh build            # Build Docker image only (vibe-trading:latest)
#   ./deploy.sh push <registry>  # Build and push to remote Docker registry / GHCR
#   ./deploy.sh remote <user@ip> # Deploy directly to remote VPS via SSH
#
# ============================================================================

set -euo pipefail

# ANSI color styling
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

IMAGE_NAME="vibe-trading"
IMAGE_TAG="${IMAGE_TAG:-latest}"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
PORT="${PORT:-3000}"
CONTAINER_NAME="vibe-trading-app"

function print_banner() {
  echo -e "${CYAN}${BOLD}"
  echo "======================================================================"
  echo "       🚀  VIBE-TRADING DOCKER BUILD & DEPLOYMENT SYSTEM              "
  echo "======================================================================"
  echo -e "${NC}"
}

function build_image() {
  echo -e "${YELLOW}[1/3] 🔨 Building Production Multi-Stage Docker Image: ${BOLD}${FULL_IMAGE}${NC}..."
  
  # Ensure frontend passes TypeScript lint checks before bundling
  if [ -f "package.json" ]; then
    echo -e "${BLUE}  -> Verifying TypeScript build integrity...${NC}"
    npm run build
  fi

  docker build \
    -t "${FULL_IMAGE}" \
    -t "${IMAGE_NAME}:production" \
    -f Dockerfile .

  echo -e "${GREEN}✓ Docker image built successfully: ${BOLD}${FULL_IMAGE}${NC}\n"
}

function run_standalone() {
  build_image
  echo -e "${YELLOW}[2/3] 🔄 Managing container lifecycle (${CONTAINER_NAME})...${NC}"
  
  # Stop and remove existing container if running
  if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${BLUE}  -> Stopping existing container...${NC}"
    docker stop "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rm "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi

  echo -e "${YELLOW}[3/3] 🚀 Starting standalone production container on port ${PORT}...${NC}"
  docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    -p "${PORT}:3000" \
    -e NODE_ENV=production \
    -e PORT=3000 \
    -e HOST=0.0.0.0 \
    -v vibe_app_data:/app/data \
    -v vibe_app_logs:/app/logs \
    "${FULL_IMAGE}"

  echo -e "\n${GREEN}======================================================================${NC}"
  echo -e "${GREEN}✅ Deployment successful! Container is up and healthy.${NC}"
  echo -e "   🌐 Local Access:   ${CYAN}http://localhost:${PORT}${NC}"
  echo -e "   📋 View Logs:      ${BOLD}docker logs -f ${CONTAINER_NAME}${NC}"
  echo -e "   🛑 Stop Service:   ${BOLD}docker stop ${CONTAINER_NAME}${NC}"
  echo -e "${GREEN}======================================================================${NC}\n"
}

function run_compose() {
  echo -e "${YELLOW}🐳 Deploying full microservice stack (App + PostgreSQL + Nginx + Certbot)...${NC}"
  docker compose -f docker-compose.yml up -d --build
  
  echo -e "\n${GREEN}======================================================================${NC}"
  echo -e "${GREEN}✅ Full stack deployed via Docker Compose!${NC}"
  echo -e "   🌐 Services:       App (Port 3000), DB (PostgreSQL 5432), Nginx (80/443)"
  echo -e "   📋 View Status:    ${BOLD}docker compose ps${NC}"
  echo -e "   📋 Stream Logs:    ${BOLD}docker compose logs -f vibe-trading${NC}"
  echo -e "   🛑 Stop Stack:     ${BOLD}docker compose down${NC}"
  echo -e "${GREEN}======================================================================${NC}\n"
}

function push_image() {
  local REGISTRY="${1:-}"
  if [ -z "${REGISTRY}" ]; then
    echo -e "${RED}Error: Target registry required. Example: ./deploy.sh push ghcr.io/username${NC}"
    exit 1
  fi
  build_image
  local TARGET_TAG="${REGISTRY}/${FULL_IMAGE}"
  echo -e "${YELLOW}📦 Tagging & Pushing to: ${BOLD}${TARGET_TAG}${NC}..."
  docker tag "${FULL_IMAGE}" "${TARGET_TAG}"
  docker push "${TARGET_TAG}"
  echo -e "${GREEN}✓ Successfully pushed ${TARGET_TAG}${NC}\n"
}

function deploy_remote() {
  local REMOTE_HOST="${1:-}"
  local REMOTE_DIR="${2:-/opt/vibe-trading}"
  
  if [ -z "${REMOTE_HOST}" ]; then
    echo -e "${RED}Error: Remote host destination required. Example: ./deploy.sh remote root@123.45.67.89${NC}"
    exit 1
  fi

  echo -e "${YELLOW}📡 Deploying to remote VPS: ${BOLD}${REMOTE_HOST}:${REMOTE_DIR}${NC}..."
  
  # Rsync source files excluding local binaries and caches
  rsync -avz --delete \
    --exclude 'node_modules' \
    --exclude 'frontend/node_modules' \
    --exclude '.git' \
    --exclude 'logs/*' \
    --exclude 'data/*' \
    ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

  # Execute remote compose restart
  ssh "${REMOTE_HOST}" "cd ${REMOTE_DIR} && docker compose -f docker-compose.yml up -d --build"
  
  echo -e "${GREEN}✅ Remote deployment to ${REMOTE_HOST} complete!${NC}\n"
}

print_banner

CMD="${1:-run}"

case "${CMD}" in
  build)
    build_image
    ;;
  compose)
    run_compose
    ;;
  push)
    push_image "${2:-}"
    ;;
  remote)
    deploy_remote "${2:-}" "${3:-/opt/vibe-trading}"
    ;;
  run|*)
    run_standalone
    ;;
esac
