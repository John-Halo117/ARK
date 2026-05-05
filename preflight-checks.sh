#!/bin/bash
##############################################################################
# Production Stack Pre-flight Validation Script
# Checks: DNS, ports, directories, permissions, acme.json, .env
# Run BEFORE: docker compose up
##############################################################################

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

FAILED=0

# Counter
CHECKS=0

##############################################################################
# UTILITY FUNCTIONS
##############################################################################

check() {
  CHECKS=$((CHECKS + 1))
  echo -e "\n[CHECK $CHECKS] $1"
}

pass() {
  echo -e "${GREEN}✓ PASS${NC}: $1"
}

warn() {
  echo -e "${YELLOW}⚠ WARN${NC}: $1"
}

fail() {
  echo -e "${RED}✗ FAIL${NC}: $1"
  FAILED=$((FAILED + 1))
}

##############################################################################
# PREREQUISITES
##############################################################################

check "Docker daemon running"
if docker ps &> /dev/null; then
  pass "Docker daemon is accessible"
else
  fail "Docker daemon not running or not accessible"
  exit 1
fi

check "docker-compose installed"
if docker compose version &> /dev/null; then
  pass "docker-compose is installed"
else
  fail "docker-compose not found"
  exit 1
fi

##############################################################################
# ENVIRONMENT FILE
##############################################################################

check ".env file exists"
if [ -f .env ]; then
  pass ".env file found"
else
  fail ".env file not found; copy from example and configure"
fi

check "CHANGE_ME values in .env"
if grep -q "CHANGE_ME" .env 2>/dev/null; then
  fail "CHANGE_ME placeholders still present in .env; update before deploy"
else
  pass "No CHANGE_ME placeholders in .env"
fi

##############################################################################
# DOMAIN & DNS
##############################################################################

check "Domain configuration"
DOMAIN=$(grep "^DOMAIN=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' ')
if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "music.example.com" ]; then
  warn "Domain not set or using example.com; update DOMAIN in .env"
else
  pass "Domain configured: $DOMAIN"

  # Check DNS resolution
  check "DNS resolution for $DOMAIN"
  if host "$DOMAIN" &> /dev/null || nslookup "$DOMAIN" &> /dev/null; then
    pass "DNS resolves for $DOMAIN"
  else
    fail "DNS does not resolve for $DOMAIN; add A record pointing to this server"
  fi
fi

##############################################################################
# PORTS
##############################################################################

check "Port 80 available"
if ! netstat -tln 2>/dev/null | grep -q ":80 " && ! ss -tln 2>/dev/null | grep -q ":80 "; then
  pass "Port 80 is available"
else
  fail "Port 80 is already in use; stop other services"
fi

check "Port 443 available"
if ! netstat -tln 2>/dev/null | grep -q ":443 " && ! ss -tln 2>/dev/null | grep -q ":443 "; then
  pass "Port 443 is available"
else
  fail "Port 443 is already in use; stop other services"
fi

check "Port 8080 available (Traefik dashboard)"
if ! netstat -tln 2>/dev/null | grep -q ":8080 " && ! ss -tln 2>/dev/null | grep -q ":8080 "; then
  pass "Port 8080 is available"
else
  warn "Port 8080 in use; Traefik dashboard may not be accessible"
fi

##############################################################################
# DIRECTORIES & PERMISSIONS
##############################################################################

check "Traefik directory exists"
if mkdir -p /srv/traefik; then
  pass "/srv/traefik directory ready"
else
  fail "Cannot create /srv/traefik; check permissions"
fi

check "acme.json exists and has correct permissions"
ACME_FILE="/srv/traefik/acme.json"
if [ ! -f "$ACME_FILE" ]; then
  if touch "$ACME_FILE" 2>/dev/null; then
    chmod 600 "$ACME_FILE"
    pass "acme.json created with mode 600"
  else
    fail "Cannot create $ACME_FILE; check /srv/traefik permissions"
  fi
else
  PERM=$(stat -c %a "$ACME_FILE" 2>/dev/null || stat -f %A "$ACME_FILE" 2>/dev/null)
  if [ "$PERM" = "600" ]; then
    pass "acme.json exists with mode 600"
  else
    warn "acme.json has mode $PERM (should be 600); fixing..."
    if chmod 600 "$ACME_FILE" 2>/dev/null; then
      pass "Fixed acme.json permissions to 600"
    else
      fail "Cannot chmod acme.json to 600; run: sudo chmod 600 $ACME_FILE"
    fi
  fi
fi

check "Traefik logs directory"
if mkdir -p /srv/traefik/logs; then
  pass "/srv/traefik/logs directory ready"
else
  fail "Cannot create /srv/traefik/logs"
fi

check "Navidrome directories"
MUSIC_PATH=$(grep "^MUSIC_PATH=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' ')
DATA_PATH=$(grep "^DATA_PATH=" .env 2>/dev/null | cut -d'=' -f2 | tr -d ' ')

if mkdir -p "$MUSIC_PATH" "$DATA_PATH" /srv/navidrome/logs; then
  pass "Navidrome directories ready: $MUSIC_PATH, $DATA_PATH"
else
  fail "Cannot create Navidrome directories"
fi

check "Music library is readable"
if [ -d "$MUSIC_PATH" ] && [ -r "$MUSIC_PATH" ]; then
  FILE_COUNT=$(find "$MUSIC_PATH" -type f 2>/dev/null | wc -l)
  if [ "$FILE_COUNT" -gt 0 ]; then
    pass "Music library readable with $FILE_COUNT files"
  else
    warn "Music library is empty; add audio files to $MUSIC_PATH"
  fi
else
  fail "Music library $MUSIC_PATH not readable; check permissions"
fi

check "Authelia directories"
if mkdir -p /srv/authelia/data /srv/authelia/logs; then
  pass "/srv/authelia directories ready"
else
  fail "Cannot create /srv/authelia directories"
fi

check "Redis directories"
if mkdir -p /srv/redis/data /srv/redis/logs; then
  pass "/srv/redis directories ready"
else
  fail "Cannot create /srv/redis directories"
fi

check "Home Assistant directories"
if mkdir -p /srv/home-assistant/config /srv/home-assistant/logs; then
  pass "/srv/home-assistant directories ready"
else
  fail "Cannot create /srv/home-assistant directories"
fi

##############################################################################
# CONFIGURATION FILES
##############################################################################

check "docker-compose.yml exists"
if [ -f docker-compose.yml ]; then
  pass "docker-compose.yml found"

  # Validate YAML syntax
  if docker-compose config > /dev/null 2>&1; then
    pass "docker-compose.yml syntax valid"
  else
    fail "docker-compose.yml has syntax errors; run: docker-compose config"
  fi
else
  fail "docker-compose.yml not found"
fi

check "Traefik config exists"
if [ -f traefik/traefik.yml ] && [ -f traefik/dynamic.yml ]; then
  pass "Traefik configuration files found"
else
  fail "Traefik config files missing"
fi

check "Authelia config exists"
if [ -f authelia/configuration.yml ] && [ -f authelia/users_database.yml ]; then
  pass "Authelia configuration files found"
else
  fail "Authelia config files missing"
fi

check "Authelia users_database.yml permissions"
if [ -f authelia/users_database.yml ]; then
  PERM=$(stat -c %a "authelia/users_database.yml" 2>/dev/null || stat -f %A "authelia/users_database.yml" 2>/dev/null)
  if [ "$PERM" = "600" ]; then
    pass "users_database.yml has mode 600"
  else
    warn "users_database.yml has mode $PERM (should be 600 for security); chmod 600 authelia/users_database.yml"
  fi
fi

##############################################################################
# SUMMARY
##############################################################################

echo -e "\n${GREEN}═══════════════════════════════════════════${NC}"
echo "PRE-FLIGHT VALIDATION SUMMARY"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo "Total checks: $CHECKS"

if [ $FAILED -eq 0 ]; then
  echo -e "${GREEN}✓ All checks passed!${NC}"
  echo -e "\nReady to deploy. Run:\n  ${GREEN}docker compose up -d${NC}"
  exit 0
else
  echo -e "${RED}✗ $FAILED check(s) failed${NC}"
  echo -e "\nFix issues above and re-run this script."
  exit 1
fi
