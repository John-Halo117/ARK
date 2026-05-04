#!/bin/bash
##############################################################################
# WIRING SETUP - Automatically wire .env → config files
# Run ONCE after updating .env with actual values
# This script updates hardcoded placeholders with actual .env values
##############################################################################

set -e

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo "WIRING SETUP - Auto-wire .env to configs"
echo -e "${GREEN}═══════════════════════════════════════════${NC}\n"

# Load .env
if [ ! -f .env ]; then
  echo -e "${RED}✗ .env not found${NC}"
  exit 1
fi
source .env

# Validate required values
if [[ "$DOMAIN" == *"example.com"* ]] && [ "$DOMAIN" != "music.example.com" ]; then
  echo -e "${YELLOW}⚠ DOMAIN contains 'example.com': $DOMAIN${NC}"
fi

if [ "$DOMAIN" = "music.example.com" ]; then
  echo -e "${RED}✗ DOMAIN still set to default (music.example.com); update .env first${NC}"
  exit 1
fi

if [ "$TOP_LEVEL_DOMAIN" = "example.com" ]; then
  echo -e "${RED}✗ TOP_LEVEL_DOMAIN still set to default (example.com); update .env first${NC}"
  exit 1
fi

if [[ "$REDIS_PASSWORD" == *"CHANGE_ME"* ]]; then
  echo -e "${RED}✗ REDIS_PASSWORD still has CHANGE_ME; update .env first${NC}"
  exit 1
fi

if [[ "$AUTHELIA_TOTP_SECRET" == *"CHANGE_ME"* ]]; then
  echo -e "${RED}✗ AUTHELIA_TOTP_SECRET still has CHANGE_ME; update .env first${NC}"
  exit 1
fi

##############################################################################
# WIRING: traefik/traefik.yml
##############################################################################

echo "[WIRE 1] traefik/traefik.yml"

# Update email
sed -i.bak "s/email: admin@example.com/email: ${LETSENCRYPT_EMAIL}/g" traefik/traefik.yml
echo "  ✓ Updated email to: $LETSENCRYPT_EMAIL"

# Backup created; delete it
rm -f traefik/traefik.yml.bak

##############################################################################
# WIRING: traefik/dynamic.yml
##############################################################################

echo "[WIRE 2] traefik/dynamic.yml"

# Extract subdomain from DOMAIN (e.g., "music" from "music.example.com")
SUBDOMAIN=$(echo "$DOMAIN" | cut -d. -f1)
AUTH_DOMAIN="auth.$TOP_LEVEL_DOMAIN"
TRAEFIK_DOMAIN="traefik.$TOP_LEVEL_DOMAIN"

# Update CORS origins
sed -i.bak "s|https://music.example.com|https://$DOMAIN|g" traefik/dynamic.yml
sed -i.bak "s|https://auth.example.com|https://$AUTH_DOMAIN|g" traefik/dynamic.yml
sed -i.bak "s|https://traefik.example.com|https://$TRAEFIK_DOMAIN|g" traefik/dynamic.yml
echo "  ✓ Updated domain references:"
echo "    - music: $DOMAIN"
echo "    - auth: $AUTH_DOMAIN"
echo "    - traefik: $TRAEFIK_DOMAIN"

rm -f traefik/dynamic.yml.bak

##############################################################################
# WIRING: authelia/configuration.yml
##############################################################################

echo "[WIRE 3] authelia/configuration.yml"

# Update session.domain and cookies.domain
sed -i.bak "s|domain: \"example.com\"|domain: \"$TOP_LEVEL_DOMAIN\"|g" authelia/configuration.yml
echo "  ✓ Updated session.domain to: $TOP_LEVEL_DOMAIN"

# Update access_control domains
sed -i.bak "s|domain: \"auth.example.com\"|domain: \"$AUTH_DOMAIN\"|g" authelia/configuration.yml
sed -i.bak "s|domain: \"music.example.com\"|domain: \"$DOMAIN\"|g" authelia/configuration.yml
sed -i.bak "s|domain: \"traefik.example.com\"|domain: \"$TRAEFIK_DOMAIN\"|g" authelia/configuration.yml
sed -i.bak "s|domain: \"ha.example.com\"|domain: \"ha.$TOP_LEVEL_DOMAIN\"|g" authelia/configuration.yml
echo "  ✓ Updated access_control domain rules"

rm -f authelia/configuration.yml.bak

##############################################################################
# WIRING VERIFICATION
##############################################################################

echo -e "\n${GREEN}═══════════════════════════════════════════${NC}"
echo "WIRING VERIFICATION"
echo -e "${GREEN}═══════════════════════════════════════════${NC}\n"

echo "Verifying wiring..."

ISSUES=0

# Check traefik/traefik.yml
if grep -q "email: ${LETSENCRYPT_EMAIL}" traefik/traefik.yml; then
  echo -e "${GREEN}✓${NC} traefik/traefik.yml email wired"
else
  echo -e "${RED}✗${NC} traefik/traefik.yml email NOT wired"
  ISSUES=$((ISSUES + 1))
fi

# Check traefik/dynamic.yml
if grep -q "$DOMAIN" traefik/dynamic.yml; then
  echo -e "${GREEN}✓${NC} traefik/dynamic.yml domains wired"
else
  echo -e "${RED}✗${NC} traefik/dynamic.yml domains NOT wired"
  ISSUES=$((ISSUES + 1))
fi

# Check authelia/configuration.yml
if grep -q "domain: \"$TOP_LEVEL_DOMAIN\"" authelia/configuration.yml; then
  echo -e "${GREEN}✓${NC} authelia/configuration.yml session domain wired"
else
  echo -e "${RED}✗${NC} authelia/configuration.yml session domain NOT wired"
  ISSUES=$((ISSUES + 1))
fi

if grep -q "domain: \"$DOMAIN\"" authelia/configuration.yml; then
  echo -e "${GREEN}✓${NC} authelia/configuration.yml music domain wired"
else
  echo -e "${RED}✗${NC} authelia/configuration.yml music domain NOT wired"
  ISSUES=$((ISSUES + 1))
fi

if [ $ISSUES -eq 0 ]; then
  echo -e "\n${GREEN}✓ All wiring complete!${NC}"
  echo -e "\nNext steps:"
  echo "  1. Run: bash ./wiring-check.sh (validate)"
  echo "  2. Run: bash ./preflight-checks.sh (validate directories/permissions)"
  echo "  3. Run: docker compose up -d (start stack)"
  exit 0
else
  echo -e "\n${RED}✗ $ISSUES wiring issue(s) detected${NC}"
  exit 1
fi
