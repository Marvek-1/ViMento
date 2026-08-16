#!/usr/bin/env bash
# ============================================================================
# One-Command SSL Certificate Initialization for vt.mostarindustries.com
# ============================================================================

set -euo pipefail

DOMAIN="vt.mostarindustries.com"
RSA_KEY_SIZE=4096
DATA_PATH="./certbot"
EMAIL="${1:-admin@mostarindustries.com}" # Pass your email as first argument: ./init_letsencrypt.sh your-email@domain.com
STAGING=0 # Set to 1 if you want to test without hitting Let's Encrypt rate limits

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}🔐 Setting up Let's Encrypt SSL for ${GREEN}${DOMAIN}${NC}"
echo -e "${CYAN}Contact Email: ${GREEN}${EMAIL}${NC}"
echo -e "${CYAN}======================================================${NC}\n"

if [ -d "$DATA_PATH/conf/live/$DOMAIN" ]; then
  read -p "Existing certificate data found for $DOMAIN. Replace existing certificate? (y/N) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 0
  fi
fi

mkdir -p "$DATA_PATH/conf/live/$DOMAIN"
mkdir -p "$DATA_PATH/www"

# 1. Create dummy certificate to allow Nginx to start
echo -e "${YELLOW}[1/4] Creating temporary dummy certificate for Nginx bootstrap...${NC}"
path="/etc/letsencrypt/live/$DOMAIN"
docker compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$RSA_KEY_SIZE -days 1\
    -keyout '$path/privkey.pem' \
    -out '$path/fullchain.pem' \
    -subj '/CN=localhost'" certbot

# 2. Start Nginx
echo -e "\n${YELLOW}[2/4] Starting Nginx...${NC}"
docker compose up --force-recreate -d nginx

# 3. Delete dummy certificate
echo -e "\n${YELLOW}[3/4] Removing dummy certificate...${NC}"
docker compose run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$DOMAIN && \
  rm -Rf /etc/letsencrypt/archive/$DOMAIN && \
  rm -Rf /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

# 4. Request real certificate from Let's Encrypt
echo -e "\n${YELLOW}[4/4] Requesting production certificate from Let's Encrypt...${NC}"
staging_arg=""
if [ $STAGING -ne 0 ]; then
  staging_arg="--staging"
fi

docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    --email '$EMAIL' \
    -d '$DOMAIN' \
    --rsa-key-size $RSA_KEY_SIZE \
    --agree-tos \
    --force-renewal" certbot

# 5. Reload Nginx with real certificate
echo -e "\n${YELLOW}Reloading Nginx with new SSL certificate...${NC}"
docker compose exec nginx nginx -s reload

echo -e "\n${GREEN}✅ SSL certificate installed! https://${DOMAIN} is now LIVE with HTTPS!${NC}"
