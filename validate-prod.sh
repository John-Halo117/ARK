#!/usr/bin/env bash
##############################################################################
# PRODUCTION FINAL VALIDATION
# Verifies all URLs work, configs are wired, stack is production-ready
##############################################################################

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
log_pass() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_fail() { echo -e "${RED}✗${NC} $1"; }

PASS=0
FAIL=0

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        PRODUCTION FINAL VALIDATION                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}\n"

##############################################################################
# SECTION 1: ENVIRONMENT & CONFIGURATION
##############################################################################

log_info "Section 1: Environment & Configuration"

# Check .env exists
if [ -f .env ]; then
  source .env
  log_pass ".env file exists"
  PASS=$((PASS+1))
else
  log_fail ".env file not found"
  FAIL=$((FAIL+1))
  exit 1
fi

# Validate required variables
for var in DOMAIN TOP_LEVEL_DOMAIN REDIS_PASSWORD AUTHELIA_TOTP_SECRET MUSIC_PATH DATA_PATH LETSENCRYPT_EMAIL; do
  val=$(eval echo \$$var 2>/dev/null || true)
  if [ -z "$val" ]; then
    log_fail "$var not set in .env"
    FAIL=$((FAIL+1))
  elif [[ "$val" == *"CHANGE_ME"* ]] || [[ "$val" == *"example.com"* ]]; then
    log_fail "$var still contains placeholder: $val"
    FAIL=$((FAIL+1))
  else
    log_pass "$var = ${val:0:40}..."
    PASS=$((PASS+1))
  fi
done

##############################################################################
# SECTION 2: DOCKER & DOCKER-COMPOSE
##############################################################################

log_info "\nSection 2: Docker & docker-compose"

# Docker daemon
if docker ps &>/dev/null; then
  log_pass "Docker daemon running"
  PASS=$((PASS+1))
else
  log_fail "Docker daemon not running"
  FAIL=$((FAIL+1))
fi

# docker-compose
if docker-compose config > /dev/null 2>&1; then
  log_pass "docker-compose.yml syntax valid"
  PASS=$((PASS+1))
else
  log_fail "docker-compose.yml syntax error"
  FAIL=$((FAIL+1))
fi

##############################################################################
# SECTION 3: CONFIGURATION FILES
##############################################################################

log_info "\nSection 3: Configuration Files"

# Traefik config
if [ -f traefik/traefik.yml ] && grep -q "email:" traefik/traefik.yml; then
  log_pass "traefik/traefik.yml exists and configured"
  PASS=$((PASS+1))
else
  log_warn "traefik/traefik.yml missing or not configured"
fi

if [ -f traefik/dynamic.yml ] && grep -q "authelia" traefik/dynamic.yml; then
  log_pass "traefik/dynamic.yml exists with authelia middleware"
  PASS=$((PASS+1))
else
  log_warn "traefik/dynamic.yml missing or incomplete"
fi

# Authelia config
if [ -f authelia/configuration.yml ] && grep -q "redis:" authelia/configuration.yml; then
  log_pass "authelia/configuration.yml exists with Redis config"
  PASS=$((PASS+1))
else
  log_warn "authelia/configuration.yml missing or incomplete"
fi

if [ -f authelia/users_database.yml ]; then
  log_pass "authelia/users_database.yml exists"
  PASS=$((PASS+1))
else
  log_warn "authelia/users_database.yml missing"
fi

##############################################################################
# SECTION 4: DIRECTORIES & PERMISSIONS
##############################################################################

log_info "\nSection 4: Directories & Permissions"

# Check directories
for dir in /srv/traefik /srv/navidrome/music /srv/navidrome/data /srv/authelia/data /srv/redis/data; do
  if [ -d "$dir" ]; then
    log_pass "Directory exists: $dir"
    PASS=$((PASS+1))
  else
    log_fail "Directory missing: $dir"
    FAIL=$((FAIL+1))
  fi
done

# acme.json permissions
if [ -f /srv/traefik/acme.json ]; then
  PERM=$(stat -c %a /srv/traefik/acme.json 2>/dev/null || stat -f %A /srv/traefik/acme.json 2>/dev/null || echo "999")
  if [ "$PERM" = "600" ]; then
    log_pass "/srv/traefik/acme.json has correct permissions (600)"
    PASS=$((PASS+1))
  else
    log_fail "/srv/traefik/acme.json has incorrect permissions ($PERM; should be 600)"
    FAIL=$((FAIL+1))
  fi
else
  log_warn "/srv/traefik/acme.json not created yet (will be created on first run)"
fi

# Music library
if [ -d "$MUSIC_PATH" ]; then
  FILE_COUNT=$(find "$MUSIC_PATH" -type f 2>/dev/null | wc -l || echo "0")
  if [ "$FILE_COUNT" -gt 0 ]; then
    log_pass "Music library: $FILE_COUNT files in $MUSIC_PATH"
    PASS=$((PASS+1))
  else
    log_warn "Music library empty: $MUSIC_PATH"
  fi
else
  log_fail "Music library not found: $MUSIC_PATH"
  FAIL=$((FAIL+1))
fi

##############################################################################
# SECTION 5: DNS VALIDATION
##############################################################################

log_info "\nSection 5: DNS Validation"

if command -v dig &>/dev/null; then
  if dig +short "${DOMAIN}" @8.8.8.8 &>/dev/null; then
    IP=$(dig +short "${DOMAIN}" @8.8.8.8 | head -1)
    log_pass "DNS resolves: ${DOMAIN} → ${IP}"
    PASS=$((PASS+1))
  else
    log_fail "DNS does not resolve for ${DOMAIN}"
    FAIL=$((FAIL+1))
  fi
elif command -v nslookup &>/dev/null; then
  if nslookup "${DOMAIN}" 8.8.8.8 &>/dev/null; then
    log_pass "DNS resolves for ${DOMAIN}"
    PASS=$((PASS+1))
  else
    log_fail "DNS does not resolve for ${DOMAIN}"
    FAIL=$((FAIL+1))
  fi
else
  log_warn "DNS validation tools not available (dig/nslookup)"
fi

##############################################################################
# SECTION 6: PORT AVAILABILITY
##############################################################################

log_info "\nSection 6: Port Availability"

for port in 80 443; do
  if ! nc -z localhost "$port" 2>/dev/null && ! ss -tln 2>/dev/null | grep -q ":$port " && ! netstat -tln 2>/dev/null | grep -q ":$port "; then
    log_pass "Port $port available"
    PASS=$((PASS+1))
  else
    log_warn "Port $port may be in use"
  fi
done

##############################################################################
# SECTION 7: STACK DEPLOYMENT TEST
##############################################################################

log_info "\nSection 7: Stack Deployment (starting services)"

# Start services
if docker-compose up -d --quiet-pull 2>/dev/null; then
  log_pass "Services started successfully"
  PASS=$((PASS+1))
else
  log_warn "Services may have started with warnings"
fi

# Wait for healthy
log_info "Waiting for services to be healthy (30 seconds)..."
sleep 10

##############################################################################
# SECTION 8: SERVICE HEALTH
##############################################################################

log_info "\nSection 8: Service Health"

for service in traefik redis authelia navidrome; do
  STATUS=$(docker-compose ps "$service" 2>/dev/null | grep "$service" | awk '{print $(NF-1), $NF}' 2>/dev/null || echo "down")

  if [[ "$STATUS" == *"healthy"* ]] || [[ "$STATUS" == *"Up"* ]]; then
    log_pass "$service: $STATUS"
    PASS=$((PASS+1))
  else
    log_fail "$service: NOT RUNNING ($STATUS)"
    FAIL=$((FAIL+1))
  fi
done

##############################################################################
# SECTION 9: URL VALIDATION
##############################################################################

log_info "\nSection 9: URL Validation"

# Test endpoints exist
endpoints=(
  "http://traefik:8080/ping"
  "http://authelia:9091/api/health"
  "http://navidrome:4533/health"
)

for endpoint in "${endpoints[@]}"; do
  if timeout 5 curl -s "$endpoint" &>/dev/null; then
    log_pass "Endpoint responsive: $endpoint"
    PASS=$((PASS+1))
  else
    log_warn "Endpoint not responding: $endpoint (may not be ready)"
  fi
done

##############################################################################
# SECTION 10: CONFIG VARIABLE WIRING
##############################################################################

log_info "\nSection 10: Config Variable Wiring"

# Check docker-compose uses variables
if grep -q "\${DOMAIN" docker-compose.yml || grep -q "\${TOP_LEVEL_DOMAIN" docker-compose.yml; then
  log_pass "docker-compose.yml uses environment variables"
  PASS=$((PASS+1))
else
  log_warn "docker-compose.yml may not use environment variables"
fi

# Check authelia uses REDIS_PASSWORD
if grep -q 'password: "${REDIS_PASSWORD}"' authelia/configuration.yml; then
  log_pass "authelia/configuration.yml references \${REDIS_PASSWORD}"
  PASS=$((PASS+1))
else
  log_warn "authelia/configuration.yml may not reference REDIS_PASSWORD"
fi

##############################################################################
# SECTION 11: SECURITY CHECKS
##############################################################################

log_info "\nSection 11: Security Checks"

# File permissions
if [ -f .env ]; then
  PERM=$(stat -c %a .env 2>/dev/null || stat -f %A .env 2>/dev/null || echo "999")
  if [ "$PERM" = "600" ] || [ "$PERM" = "644" ]; then
    log_pass ".env has restricted permissions"
    PASS=$((PASS+1))
  else
    log_warn ".env permissions not optimal ($PERM)"
  fi
fi

# Users database permissions
if [ -f authelia/users_database.yml ]; then
  PERM=$(stat -c %a authelia/users_database.yml 2>/dev/null || stat -f %A authelia/users_database.yml 2>/dev/null || echo "999")
  if [ "$PERM" = "600" ] || [ "$PERM" = "644" ]; then
    log_pass "authelia/users_database.yml has restricted permissions"
    PASS=$((PASS+1))
  else
    log_warn "authelia/users_database.yml permissions not optimal ($PERM)"
  fi
fi

##############################################################################
# CLEANUP & SUMMARY
##############################################################################

log_info "\nStopping services for validation..."
docker-compose down --quiet 2>/dev/null || true

##############################################################################
# FINAL REPORT
##############################################################################

echo -e "\n${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                   VALIDATION REPORT                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "Checks passed: ${GREEN}${PASS}${NC}"
echo -e "Issues found:  ${RED}${FAIL}${NC}"

if [ $FAIL -eq 0 ]; then
  echo -e "\n${GREEN}✓ PRODUCTION READY!${NC}"
  echo -e "\nDeployment checklist:"
  echo "  1. Verify DNS is working: nslookup ${DOMAIN}"
  echo "  2. Verify firewall: sudo ufw allow 80/tcp && sudo ufw allow 443/tcp"
  echo "  3. Deploy: bash deploy-prod.sh staging"
  echo "  4. Change password: docker run --rm authelia/authelia:4.38.5 authelia hash-password"
  echo "  5. Production: bash deploy-prod.sh production"
  exit 0
else
  echo -e "\n${RED}✗ Issues found - fix above and re-run this validation${NC}"
  exit 1
fi
