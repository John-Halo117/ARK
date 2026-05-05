#!/usr/bin/env bash
##############################################################################
# PRODUCTION DEPLOYMENT SCRIPT
# Full validation, init, and deployment
# Usage: bash deploy-prod.sh [staging|production]
##############################################################################

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_pass() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_fail() { echo -e "${RED}✗${NC} $1"; }

DEPLOY_ENV="${1:-production}"

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          PRODUCTION STACK DEPLOYMENT (${DEPLOY_ENV^^})            ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}\n"

##############################################################################
# 1. VERIFY ENVIRONMENT
##############################################################################

log_info "Verifying environment..."

if [ "$DEPLOY_ENV" != "staging" ] && [ "$DEPLOY_ENV" != "production" ]; then
  log_fail "Invalid environment: $DEPLOY_ENV (use: staging or production)"
  exit 1
fi

# Check .env exists
if [ ! -f .env ]; then
  log_warn ".env not found"
  if [ -f .env.prod ]; then
    log_info "Copying .env.prod to .env"
    cp .env.prod .env
  else
    log_fail "No .env or .env.prod found"
    exit 1
  fi
fi

source .env

# Validate required variables
REQUIRED=("DOMAIN" "TOP_LEVEL_DOMAIN" "REDIS_PASSWORD" "AUTHELIA_TOTP_SECRET")
for var in "${REQUIRED[@]}"; do
  val=$(eval echo \$$var 2>/dev/null || true)
  if [ -z "$val" ] || [[ "$val" == *"CHANGE_ME"* ]]; then
    log_fail "$var not set; edit .env"
    exit 1
  fi
done

log_pass "Environment variables valid"

##############################################################################
# 2. RUN INITIALIZATION
##############################################################################

log_info "\nRunning initialization (init-prod.sh)..."

if bash init-prod.sh; then
  log_pass "Initialization complete"
else
  log_fail "Initialization failed"
  exit 1
fi

##############################################################################
# 3. UPDATE LETSENCRYPT ENVIRONMENT
##############################################################################

log_info "\nConfiguring Let's Encrypt environment..."

if [ "$DEPLOY_ENV" = "staging" ]; then
  log_warn "Using Let's Encrypt STAGING (test certificates)"
  sed -i.bak 's|https://acme-v02.api.letsencrypt.org/directory|https://acme-staging-v02.api.letsencrypt.org/directory|g' traefik/traefik.yml
  rm -f traefik/traefik.yml.bak
  log_pass "Staging certificates enabled"
else
  log_pass "Using Let's Encrypt PRODUCTION (real certificates)"
fi

##############################################################################
# 4. PULL LATEST IMAGES
##############################################################################

log_info "\nPulling latest container images..."

docker-compose pull || log_warn "Failed to pull some images (may be offline)"
log_pass "Images pulled"

##############################################################################
# 5. START SERVICES (with healthcheck wait)
##############################################################################

log_info "\nStarting services..."

# Stop any existing containers
docker-compose down 2>/dev/null || true

# Start in background
docker-compose up -d

log_pass "Services started"

##############################################################################
# 6. WAIT FOR HEALTHY
##############################################################################

log_info "\nWaiting for services to be healthy..."

WAIT_TIME=0
MAX_WAIT=120

while [ $WAIT_TIME -lt $MAX_WAIT ]; do
  HEALTHY=$(docker-compose ps --services --status running | wc -l)
  TOTAL=$(docker-compose config --services | wc -l)

  if [ "$HEALTHY" -eq "$TOTAL" ]; then
    log_pass "All services running"
    break
  fi

  sleep 5
  WAIT_TIME=$((WAIT_TIME + 5))
  echo -n "."
done

echo ""

##############################################################################
# 7. VALIDATE SERVICES
##############################################################################

log_info "\nValidating service health..."

UNHEALTHY=0
for service in traefik redis authelia navidrome; do
  STATUS=$(docker-compose ps "$service" 2>/dev/null | grep "$service" | awk '{print $NF}' || echo "down")

  if [[ "$STATUS" == *"healthy"* ]] || [[ "$STATUS" == *"(healthy)"* ]]; then
    log_pass "$service: healthy"
  elif [[ "$STATUS" == *"Up"* ]]; then
    log_warn "$service: running (health check pending)"
  else
    log_fail "$service: $STATUS"
    UNHEALTHY=$((UNHEALTHY + 1))
  fi
done

##############################################################################
# 8. TEST ENDPOINTS
##############################################################################

log_info "\nTesting endpoints..."

sleep 5  # Let services fully initialize

# Test Traefik
if curl -s -k "https://traefik.${TOP_LEVEL_DOMAIN}" -I 2>/dev/null | grep -q "401\|200\|302"; then
  log_pass "Traefik dashboard accessible"
else
  log_warn "Traefik dashboard not responding yet (may take 30+ seconds)"
fi

# Test Authelia
if curl -s "http://authelia:9091/api/health" 2>/dev/null | grep -q "ok"; then
  log_pass "Authelia health check passed"
else
  log_warn "Authelia health check pending"
fi

# Test Navidrome
if curl -s "http://navidrome:4533/health" 2>/dev/null | grep -q "ok"; then
  log_pass "Navidrome health check passed"
else
  log_warn "Navidrome health check pending"
fi

##############################################################################
# 9. VERIFY CERTIFICATES
##############################################################################

log_info "\nVerifying Let's Encrypt certificates..."

if [ -f /srv/traefik/acme.json ]; then
  CERT_COUNT=$(grep -c "\"domain\"" /srv/traefik/acme.json 2>/dev/null || echo "0")
  if [ "$CERT_COUNT" -gt 0 ]; then
    log_pass "Certificates found ($CERT_COUNT domains)"
  else
    log_warn "No certificates yet (will be generated on first request, ~30 seconds)"
  fi
else
  log_warn "acme.json not found (will be created on first HTTPS request)"
fi

##############################################################################
# SUMMARY
##############################################################################

echo -e "\n${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                   DEPLOYMENT COMPLETE                        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"

echo -e "\n${BLUE}Deployment Info:${NC}"
echo "  Environment:     ${DEPLOY_ENV^^}"
echo "  Domain:          ${DOMAIN}"
echo "  Music Library:   ${MUSIC_PATH}"
echo "  Data Directory:  ${DATA_PATH}"

echo -e "\n${BLUE}Service URLs:${NC}"
echo "  Music:          https://music.${DOMAIN}"
echo "  Dashboard:      https://traefik.${TOP_LEVEL_DOMAIN}/dashboard/"
echo "  Auth:           https://auth.${TOP_LEVEL_DOMAIN}"
echo "  Home Assistant: http://$(hostname -I | awk '{print $1}'):8123"

echo -e "\n${BLUE}Default Credentials:${NC}"
echo "  Username:       admin"
echo "  Password:       authelia (CHANGE IMMEDIATELY)"
echo "  To change:      docker run --rm authelia/authelia:4.38.5 authelia hash-password"

echo -e "\n${BLUE}Next Steps:${NC}"
echo "  1. Change admin password:"
echo "     docker run --rm authelia/authelia:4.38.5 authelia hash-password"
echo "  2. Update authelia/users_database.yml with new hash"
echo "  3. Restart Authelia: docker-compose restart authelia"
echo "  4. Enable TOTP (2FA) in user settings"
echo "  5. Monitor logs: docker-compose logs -f"

echo -e "\n${BLUE}Logs:${NC}"
echo "  Traefik:  docker-compose logs traefik"
echo "  Authelia: docker-compose logs authelia"
echo "  Navidrome: docker-compose logs navidrome"
echo "  All:      docker-compose logs -f"

echo -e "\n${BLUE}Maintenance:${NC}"
echo "  Stop:     docker-compose down"
echo "  Restart:  docker-compose restart"
echo "  Update:   docker-compose pull && docker-compose up -d"
echo "  Cleanup:  docker system prune"

if [ $UNHEALTHY -eq 0 ]; then
  echo -e "\n${GREEN}✓ All services healthy!${NC}\n"
  exit 0
else
  echo -e "\n${YELLOW}⚠ Some services unhealthy; check logs${NC}"
  echo "  docker-compose logs"
  exit 1
fi
