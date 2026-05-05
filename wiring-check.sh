#!/bin/bash
##############################################################################
# WIRING VALIDATION SCRIPT
# Checks that all .env variables are correctly wired to config files
# Run AFTER: updating .env
# Before: docker compose up
##############################################################################

set -e

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

FAILED=0

echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo "WIRING VALIDATION"
echo -e "${GREEN}═══════════════════════════════════════════${NC}\n"

# Load .env
if [ ! -f .env ]; then
  echo -e "${RED}✗ .env not found${NC}"
  exit 1
fi
source .env

##############################################################################
# DOMAIN VALIDATION
##############################################################################

echo -e "\n[CHECK 1] DOMAIN & TOP_LEVEL_DOMAIN wiring"
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "music.example.com" ]; then
  echo -e "${YELLOW}⚠ DOMAIN not set${NC}: $DOMAIN"
  FAILED=$((FAILED + 1))
else
  echo -e "${GREEN}✓ DOMAIN${NC}: $DOMAIN"
fi

if [ -z "$TOP_LEVEL_DOMAIN" ] || [ "$TOP_LEVEL_DOMAIN" = "example.com" ]; then
  echo -e "${YELLOW}⚠ TOP_LEVEL_DOMAIN not set${NC}: $TOP_LEVEL_DOMAIN"
  FAILED=$((FAILED + 1))
else
  echo -e "${GREEN}✓ TOP_LEVEL_DOMAIN${NC}: $TOP_LEVEL_DOMAIN"
fi

# Validate TOP_LEVEL_DOMAIN is parent of DOMAIN
if [[ "$DOMAIN" == *"$TOP_LEVEL_DOMAIN" ]]; then
  echo -e "${GREEN}✓ DOMAIN is subdomain of TOP_LEVEL_DOMAIN${NC}"
else
  echo -e "${RED}✗ DOMAIN ($DOMAIN) is NOT subdomain of TOP_LEVEL_DOMAIN ($TOP_LEVEL_DOMAIN)${NC}"
  FAILED=$((FAILED + 1))
fi

##############################################################################
# REDIS PASSWORD VALIDATION
##############################################################################

echo -e "\n[CHECK 2] REDIS_PASSWORD wiring"
if [[ "$REDIS_PASSWORD" == *"CHANGE_ME"* ]] || [ -z "$REDIS_PASSWORD" ]; then
  echo -e "${RED}✗ REDIS_PASSWORD not set${NC}: $REDIS_PASSWORD"
  FAILED=$((FAILED + 1))
else
  PASS_LEN=${#REDIS_PASSWORD}
  echo -e "${GREEN}✓ REDIS_PASSWORD set${NC} (${PASS_LEN} chars)"

  # Check if in docker-compose.yml
  if grep -q "REDIS_PASSWORD:" docker-compose.yml && grep -q "AUTHELIA_LOG_LEVEL" docker-compose.yml; then
    echo -e "${GREEN}✓ REDIS_PASSWORD passed to authelia environment${NC}"
  else
    echo -e "${YELLOW}⚠ REDIS_PASSWORD may not be passed to authelia${NC}"
  fi

  # Check if in authelia/configuration.yml
  if grep -q 'password: "${REDIS_PASSWORD}"' authelia/configuration.yml; then
    echo -e "${GREEN}✓ REDIS_PASSWORD used in authelia/configuration.yml${NC}"
  else
    echo -e "${YELLOW}⚠ REDIS_PASSWORD not referenced in authelia/configuration.yml${NC}"
  fi
fi

##############################################################################
# AUTHELIA TOTP SECRET VALIDATION
##############################################################################

echo -e "\n[CHECK 3] AUTHELIA_TOTP_SECRET wiring"
if [[ "$AUTHELIA_TOTP_SECRET" == *"CHANGE_ME"* ]] || [ -z "$AUTHELIA_TOTP_SECRET" ]; then
  echo -e "${RED}✗ AUTHELIA_TOTP_SECRET not set${NC}: $AUTHELIA_TOTP_SECRET"
  FAILED=$((FAILED + 1))
else
  SECRET_LEN=${#AUTHELIA_TOTP_SECRET}
  echo -e "${GREEN}✓ AUTHELIA_TOTP_SECRET set${NC} (${SECRET_LEN} chars)"

  # Check if in docker-compose.yml
  if grep -q "AUTHELIA_TOTP_SECRET:" docker-compose.yml; then
    echo -e "${GREEN}✓ AUTHELIA_TOTP_SECRET passed to authelia environment${NC}"
  else
    echo -e "${YELLOW}⚠ AUTHELIA_TOTP_SECRET may not be passed to authelia${NC}"
  fi

  # Check if in authelia/configuration.yml
  if grep -q 'secret: "${AUTHELIA_TOTP_SECRET}"' authelia/configuration.yml; then
    echo -e "${GREEN}✓ AUTHELIA_TOTP_SECRET used in authelia/configuration.yml${NC}"
  else
    echo -e "${YELLOW}⚠ AUTHELIA_TOTP_SECRET not referenced in authelia/configuration.yml${NC}"
  fi
fi

##############################################################################
# MUSIC PATHS VALIDATION
##############################################################################

echo -e "\n[CHECK 4] MUSIC_PATH & DATA_PATH wiring"
if [ -z "$MUSIC_PATH" ]; then
  echo -e "${RED}✗ MUSIC_PATH not set${NC}"
  FAILED=$((FAILED + 1))
else
  echo -e "${GREEN}✓ MUSIC_PATH${NC}: $MUSIC_PATH"

  if [ -d "$MUSIC_PATH" ]; then
    echo -e "${GREEN}✓ $MUSIC_PATH exists${NC}"
  else
    echo -e "${RED}✗ $MUSIC_PATH does NOT exist${NC}"
    FAILED=$((FAILED + 1))
  fi
fi

if [ -z "$DATA_PATH" ]; then
  echo -e "${RED}✗ DATA_PATH not set${NC}"
  FAILED=$((FAILED + 1))
else
  echo -e "${GREEN}✓ DATA_PATH${NC}: $DATA_PATH"

  if [ -d "$DATA_PATH" ]; then
    echo -e "${GREEN}✓ $DATA_PATH exists${NC}"
  else
    echo -e "${RED}✗ $DATA_PATH does NOT exist${NC}"
    FAILED=$((FAILED + 1))
  fi
fi

##############################################################################
# CONFIG FILE WIRING CHECKS
##############################################################################

echo -e "\n[CHECK 5] traefik/traefik.yml wiring"
if grep -q "email: admin@example.com" traefik/traefik.yml; then
  echo -e "${YELLOW}⚠ traefik.yml has hardcoded email (admin@example.com); update to $LETSENCRYPT_EMAIL${NC}"
  FAILED=$((FAILED + 1))
else
  echo -e "${GREEN}✓ traefik.yml email not hardcoded to default${NC}"
fi

echo -e "\n[CHECK 6] traefik/dynamic.yml domain references"
GREP_COUNT=$(grep -c "music.example.com" traefik/dynamic.yml || true)
if [ "$GREP_COUNT" -gt 0 ]; then
  echo -e "${YELLOW}⚠ traefik/dynamic.yml has default domain references; update to match DOMAIN=$DOMAIN${NC}"
else
  echo -e "${GREEN}✓ traefik/dynamic.yml domain references checked${NC}"
fi

echo -e "\n[CHECK 7] authelia/configuration.yml wiring"
# Check domain in session.domain
if grep -q 'domain: "example.com"' authelia/configuration.yml; then
  echo -e "${YELLOW}⚠ authelia/configuration.yml has hardcoded domain (example.com); update to $TOP_LEVEL_DOMAIN${NC}"
  FAILED=$((FAILED + 1))
else
  echo -e "${GREEN}✓ authelia/configuration.yml domain checked${NC}"
fi

# Check REDIS_PASSWORD reference
if grep -q 'password: "${REDIS_PASSWORD}"' authelia/configuration.yml; then
  echo -e "${GREEN}✓ authelia/configuration.yml uses \${REDIS_PASSWORD}${NC}"
else
  echo -e "${RED}✗ authelia/configuration.yml doesn't reference \${REDIS_PASSWORD}${NC}"
  FAILED=$((FAILED + 1))
fi

# Check access control domains
GREP_AUTH=$(grep -c "auth.example.com" authelia/configuration.yml || true)
GREP_MUSIC=$(grep -c "music.example.com" authelia/configuration.yml || true)
if [ "$GREP_AUTH" -gt 0 ] || [ "$GREP_MUSIC" -gt 0 ]; then
  echo -e "${YELLOW}⚠ authelia/configuration.yml has default domain references; update to match DOMAIN=$DOMAIN${NC}"
else
  echo -e "${GREEN}✓ authelia/configuration.yml domain references checked${NC}"
fi

##############################################################################
# DOCKER-COMPOSE WIRING
##############################################################################

echo -e "\n[CHECK 8] docker-compose.yml variable expansion"
if grep -q 'DOMAIN=${DOMAIN' docker-compose.yml; then
  echo -e "${GREEN}✓ docker-compose.yml uses \${DOMAIN} in labels${NC}"
else
  echo -e "${YELLOW}⚠ docker-compose.yml may not expand \${DOMAIN}${NC}"
fi

if grep -q 'REDIS_PASSWORD:' docker-compose.yml; then
  echo -e "${GREEN}✓ docker-compose.yml passes REDIS_PASSWORD to authelia${NC}"
else
  echo -e "${RED}✗ docker-compose.yml doesn't pass REDIS_PASSWORD to authelia${NC}"
  FAILED=$((FAILED + 1))
fi

if grep -q 'AUTHELIA_TOTP_SECRET:' docker-compose.yml; then
  echo -e "${GREEN}✓ docker-compose.yml passes AUTHELIA_TOTP_SECRET to authelia${NC}"
else
  echo -e "${RED}✗ docker-compose.yml doesn't pass AUTHELIA_TOTP_SECRET to authelia${NC}"
  FAILED=$((FAILED + 1))
fi

if grep -q 'MUSIC_PATH' docker-compose.yml; then
  echo -e "${GREEN}✓ docker-compose.yml uses \${MUSIC_PATH}${NC}"
else
  echo -e "${RED}✗ docker-compose.yml doesn't use \${MUSIC_PATH}${NC}"
  FAILED=$((FAILED + 1))
fi

if grep -q 'DATA_PATH' docker-compose.yml; then
  echo -e "${GREEN}✓ docker-compose.yml uses \${DATA_PATH}${NC}"
else
  echo -e "${RED}✗ docker-compose.yml doesn't use \${DATA_PATH}${NC}"
  FAILED=$((FAILED + 1))
fi

##############################################################################
# SUMMARY
##############################################################################

echo -e "\n${GREEN}═══════════════════════════════════════════${NC}"
echo "WIRING VALIDATION SUMMARY"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"

if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}✓ All wiring checks passed!${NC}"
  exit 0
else
  echo -e "${RED}✗ $FAILED wiring issue(s) found${NC}"
  echo -e "\nNext steps:"
  echo "  1. Review failures above"
  echo "  2. Update .env with actual values (not defaults)"
  echo "  3. Update hardcoded config files:"
  echo "     - traefik/traefik.yml: email, cert resolver"
  echo "     - traefik/dynamic.yml: domain references in security headers"
  echo "     - authelia/configuration.yml: session.domain, access_control rules"
  echo "  4. Run this script again"
  exit 1
fi
