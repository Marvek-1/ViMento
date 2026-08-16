#!/usr/bin/env bash
# ============================================================================
# Vibe-Trading: VPS Host Initialization Script
# Run this ONCE on your remote VPS (Ubuntu / Debian) to install Docker,
# firewall rules, and configure 24/7 service auto-restart on system reboot.
#
# Usage (run on VPS):
#   curl -fsSL https://raw.githubusercontent.com/.../vps_setup.sh | sudo bash
#   OR
#   sudo bash scripts/vps_setup.sh
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}⚙️  Vibe-Trading VPS Host System Preparation${NC}"
echo -e "${CYAN}======================================================${NC}\n"

# Ensure running as root
if [ "$(id -u)" -ne 0 ]; then
  echo -e "${RED}Error: This script must be run as root (use sudo).${NC}"
  exit 1
fi

echo -e "${YELLOW}[1/4] Updating package repos and installing prerequisites...${NC}"
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    htop \
    ufw \
    rsync \
    git

# Install Docker Engine & Compose plugin if not present
if ! command -v docker >/dev/null 2>&1; then
  echo -e "\n${YELLOW}[2/4] Installing official Docker Engine & Compose...${NC}"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes 2>/dev/null || true
  chmod a+r /etc/apt/keyrings/docker.gpg

  ARCH=$(dpkg --print-architecture)
  DISTRO=$(. /etc/os-release && echo "$ID")
  VERSION_CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")

  echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${DISTRO} ${VERSION_CODENAME} stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable docker
  systemctl start docker
  echo -e "${GREEN}✓ Docker Engine installed and running.${NC}"
else
  echo -e "${GREEN}✓ Docker is already installed.${NC}"
fi

# Step 3: Create directory tree for Vibe-Trading
echo -e "\n${YELLOW}[3/4] Creating application workspace at /opt/vibe-trading...${NC}"
mkdir -p /opt/vibe-trading/data /opt/vibe-trading/logs /opt/vibe-trading/secrets
chmod -R 755 /opt/vibe-trading

# Step 4: Configure UFW Firewall (SSH + Web Port 3000 + API 8899)
echo -e "\n${YELLOW}[4/4] Configuring firewall (UFW)...${NC}"
if command -v ufw >/dev/null 2>&1; then
  ufw allow 22/tcp comment 'SSH' || true
  ufw allow 3000/tcp comment 'Vibe Trading Web App' || true
  ufw allow 8899/tcp comment 'Trading API' || true
  ufw --force enable || true
  echo -e "${GREEN}✓ Firewall configured (Ports 22, 3000, 8899 open).${NC}"
fi

# Create systemd auto-restart watchdog
cat << 'EOF' > /etc/systemd/system/vibe-trading.service
[Unit]
Description=Vibe-Trading Continuous Autonomous Trading Daemon
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/vibe-trading
ExecStart=/usr/bin/docker compose -f docker-compose.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vibe-trading.service

echo -e "\n${CYAN}======================================================${NC}"
echo -e "${GREEN}✅ VPS Host is fully primed and ready for continuous trading!${NC}"
echo -e "${CYAN}Deploy anytime from your local machine using:${NC}"
echo -e "  ./scripts/sync_to_vps.sh user@<vps-ip> /opt/vibe-trading"
echo -e "${CYAN}======================================================${NC}"
