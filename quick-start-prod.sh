#!/usr/bin/env bash
##############################################################################
# PRODUCTION QUICK START - 5 MINUTE DEPLOY
# For experienced DevOps engineers
##############################################################################

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}╔═══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     PRODUCTION QUICK START (5-MINUTE DEPLOY)         ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════╝${NC}\n"

# Check Docker
docker ps &>/dev/null || { echo -e "${RED}✗ Docker not running${NC}"; exit 1; }

# Load environment
[ -f .env ] || cp .env.prod .env
source .env

# Validate required vars
for var in DOMAIN TOP_LEVEL_DOMAIN REDIS_PASSWORD AUTHELIA_TOTP_SECRET; do
  val=$(eval echo \$$var 2>/dev/null || true)
  [ -z "$val" ] || [[ "$val" == *"CHANGE_ME"* ]] && { echo -e "${RED}✗ $var not set in .env${NC}"; exit 1; }
done

# Generate configs
mkdir -p /srv/{traefik,navidrome/{music,data},authelia/data,redis/data,home-assistant/config}
mkdir -p /srv/{traefik,navidrome,authelia,redis,home-assistant}/logs
touch /srv/traefik/acme.json && chmod 600 /srv/traefik/acme.json

# Run init
echo -e "${BLUE}ℹ${NC} Initializing (auto-generates configs)..."
bash init-prod.sh > /dev/null 2>&1

# Deploy
echo -e "${BLUE}ℹ${NC} Deploying stack..."
docker-compose up -d --quiet-pull

# Wait for healthy
for i in {1..30}; do
  RUNNING=$(docker-compose ps --services --status running 2>/dev/null | wc -l)
  TOTAL=$(docker-compose config --services 2>/dev/null | wc -l)
  [ "$RUNNING" -eq "$TOTAL" ] && break
  sleep 2
done

# Status
echo -e "\n${GREEN}✓ Stack deployed!${NC}\n"
docker-compose ps

# Instructions
echo -e "\n${BLUE}Quick Links:${NC}"
echo "  Music:     https://music.${DOMAIN}"
echo "  Dashboard: https://traefik.${TOP_LEVEL_DOMAIN}/dashboard/"
echo "  Logs:      docker-compose logs -f"

echo -e "\n${BLUE}Next Steps:${NC}"
echo "  1. Change password: docker run --rm authelia/authelia:4.38.5 authelia hash-password"
echo "  2. Update authelia/users_database.yml with new hash"
echo "  3. Restart: docker-compose restart authelia"
