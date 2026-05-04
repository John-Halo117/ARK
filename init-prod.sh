#!/usr/bin/env bash
##############################################################################
# PRODUCTION INIT SCRIPT
# Initializes and validates all config files, env vars, directories, certs
# Run ONCE before first deployment: bash init-prod.sh
##############################################################################

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging
log_info() { echo -e "${BLUE}ℹ${NC} $1"; }
log_pass() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_fail() { echo -e "${RED}✗${NC} $1"; }

ISSUES=0

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        PRODUCTION STACK INITIALIZATION & VALIDATION          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}\n"

##############################################################################
# 1. CHECK PREREQUISITES
##############################################################################

log_info "Checking prerequisites..."

command -v docker &>/dev/null || { log_fail "Docker not installed"; exit 1; }
log_pass "Docker installed"

command -v docker-compose &>/dev/null || { log_fail "docker-compose not found"; exit 1; }
log_pass "docker-compose installed"

docker ps &>/dev/null || { log_fail "Docker daemon not running"; exit 1; }
log_pass "Docker daemon running"

##############################################################################
# 2. LOAD & VALIDATE .env
##############################################################################

log_info "\nValidating .env configuration..."

if [ ! -f .env ]; then
  log_warn ".env not found; creating from .env.example"
  cp .env.example .env
  log_fail "Please edit .env with your values and re-run this script"
  exit 1
fi

# Source .env
set +e
source .env 2>/dev/null
set -e

# Required variables
REQUIRED_VARS=(
  "DOMAIN"
  "TOP_LEVEL_DOMAIN"
  "LETSENCRYPT_EMAIL"
  "REDIS_PASSWORD"
  "AUTHELIA_TOTP_SECRET"
  "MUSIC_PATH"
  "DATA_PATH"
)

for var in "${REQUIRED_VARS[@]}"; do
  val=$(eval echo \$$var 2>/dev/null || true)
  if [ -z "$val" ] || [[ "$val" == "CHANGE_ME"* ]]; then
    log_fail "$var not set or contains CHANGE_ME"
    ISSUES=$((ISSUES + 1))
  else
    log_pass "$var = ${val:0:30}..."
  fi
done

if [ $ISSUES -gt 0 ]; then
  log_fail "Fix .env and re-run"
  exit 1
fi

##############################################################################
# 3. CREATE DIRECTORIES WITH PERMISSIONS
##############################################################################

log_info "\nCreating directories..."

mkdir -p /srv/{traefik,navidrome/{music,data},authelia/data,redis/data,home-assistant/config}
mkdir -p /srv/{traefik,navidrome,authelia,redis,home-assistant}/{logs}

log_pass "Directories created"

##############################################################################
# 4. SETUP ACME.JSON WITH CORRECT PERMISSIONS
##############################################################################

log_info "\nSetting up Let's Encrypt certificate storage..."

ACME_FILE="/srv/traefik/acme.json"
if [ ! -f "$ACME_FILE" ]; then
  touch "$ACME_FILE"
  chmod 600 "$ACME_FILE"
  log_pass "acme.json created (mode 600)"
else
  # Fix permissions if needed
  PERM=$(stat -c %a "$ACME_FILE" 2>/dev/null || stat -f %A "$ACME_FILE" 2>/dev/null || true)
  if [ "$PERM" != "600" ]; then
    chmod 600 "$ACME_FILE"
    log_pass "acme.json permissions fixed (mode 600)"
  else
    log_pass "acme.json exists with correct permissions"
  fi
fi

##############################################################################
# 5. GENERATE TRAEFIK CONFIG (Hardcoded → Uses ENV substitution)
##############################################################################

log_info "\nGenerating traefik/traefik.yml..."

cat > traefik/traefik.yml << 'TRAEFIK_CONFIG'
# Traefik v3 Static Configuration
# Auto-generated; do not edit directly
# Run: bash init-prod.sh to regenerate

global:
  sendAnonymousUsage: false
  checkNewVersion: false

entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entrypoint:
          scheme: https
          permanent: true
  
  websecure:
    address: ":443"
    http:
      tls:
        certResolver: letsencrypt
        options: default
      middlewares:
        - securityHeaders@file
  
  traefik:
    address: ":8080"

certificateResolvers:
  letsencrypt:
    acme:
      email: LETSENCRYPT_EMAIL_PLACEHOLDER
      storage: /acme.json
      httpChallenge:
        entryPoint: web

providers:
  docker:
    endpoint: unix:///var/run/docker.sock
    exposedByDefault: false
    network: proxy
  
  file:
    filename: /etc/traefik/dynamic.yml
    watch: true

api:
  dashboard: true
  debug: false

log:
  level: info
  filePath: /var/log/traefik/traefik.log
  format: json

accessLog:
  filePath: /var/log/traefik/access.log
  format: json
  bufferingSize: 100
TRAEFIK_CONFIG

# Substitute email
sed -i.bak "s|LETSENCRYPT_EMAIL_PLACEHOLDER|${LETSENCRYPT_EMAIL}|g" traefik/traefik.yml
rm -f traefik/traefik.yml.bak

log_pass "traefik/traefik.yml generated"

##############################################################################
# 6. GENERATE TRAEFIK DYNAMIC CONFIG
##############################################################################

log_info "\nGenerating traefik/dynamic.yml..."

AUTH_DOMAIN="auth.${TOP_LEVEL_DOMAIN}"
TRAEFIK_DOMAIN="traefik.${TOP_LEVEL_DOMAIN}"
MUSIC_DOMAIN="music.${DOMAIN}"

cat > traefik/dynamic.yml << 'DYNAMIC_CONFIG'
# Traefik v3 Dynamic Configuration
# Auto-generated; do not edit directly
# Run: bash init-prod.sh to regenerate

http:
  middlewares:
    securityHeaders:
      headers:
        accessControlAllowOriginList: []
        accessControlAllowCredentials: true
        accessControlAllowMethods:
          - GET
          - POST
          - PUT
          - DELETE
          - OPTIONS
        accessControlMaxAge: 100
        addVaryHeader: true
        stsSeconds: 63072000
        stsIncludeSubdomains: true
        stsPreload: true
        contentTypeNosniff: true
        framedeny: true
        referrerPolicy: "strict-origin-when-cross-origin"
        contentSecurityPolicy: "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
    
    authelia:
      forwardauth:
        address: http://authelia:9091/api/authz/forward-auth
        trustForwardHeader: true
        authRequestHeaders:
          - Remote-User
          - Remote-Groups
          - Remote-Name
          - Remote-Email
        authResponseHeaders:
          - Authorization
    
    rateLimitBrute:
      rateLimit:
        average: 5
        period: 60s
        burst: 10
    
    rateLimitAPI:
      rateLimit:
        average: 100
        period: 60s
        burst: 200
    
    compression:
      compress: true

tls:
  options:
    default:
      minVersion: VersionTLS12
      cipherSuites:
        - TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256
        - TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
        - TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384
        - TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
        - TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256
        - TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256
      curvePreferences:
        - CurveP521
        - CurveP384
        - CurveP256
      sniStrict: false
DYNAMIC_CONFIG

# Add domain-specific CORS headers
cat >> traefik/dynamic.yml << CORS_CONFIG

    securityHeaders.accessControlAllowOriginList:
      - "https://${MUSIC_DOMAIN}"
      - "https://${AUTH_DOMAIN}"
      - "https://${TRAEFIK_DOMAIN}"
CORS_CONFIG

log_pass "traefik/dynamic.yml generated"

##############################################################################
# 7. GENERATE AUTHELIA CONFIG
##############################################################################

log_info "\nGenerating authelia/configuration.yml..."

cat > authelia/configuration.yml << 'AUTHELIA_CONFIG'
# Authelia v4 Configuration
# Auto-generated; do not edit directly
# Run: bash init-prod.sh to regenerate

server:
  host: 0.0.0.0
  port: 9091
  path: ""

log:
  level: info
  format: json
  file_path: /var/log/authelia/authelia.log
  keep_stdout: false

totp:
  disable: false
  issuer: Authelia
  algorithm: sha1
  digits: 6
  period: 30
  skew: 1
  secret: "${AUTHELIA_TOTP_SECRET}"

webauthn:
  disable: true

duo_api:
  disable: true

session:
  name: authelia_session
  domain: "TOP_LEVEL_DOMAIN_PLACEHOLDER"
  expiration: 3600
  inactivity: 300
  remember_me_duration: 30d
  provider: redis
  redis:
    host: redis
    port: 6379
    password: "${REDIS_PASSWORD}"
    database_index: 0
    maximum_active_connections: 10
    minimum_idle_connections: 5
    tls:
      enabled: false

regulation:
  max_retries: 3
  find_time: 2m
  ban_time: 5m

storage:
  local:
    path: /config/users_database.yml

authentication_backend:
  password_reset:
    disable: true
  refresh_interval: 5m
  file:
    path: /config/users_database.yml
    watch: true
    search:
      email: true

access_control:
  default_policy: deny
  rules:
    - domain: "AUTH_DOMAIN_PLACEHOLDER"
      path: "/api/health"
      policy: bypass
      methods: [GET]
    
    - domain: "AUTH_DOMAIN_PLACEHOLDER"
      path: "/api/authz/forward-auth"
      policy: bypass
      methods: [GET, POST]
    
    - domain: "MUSIC_DOMAIN_PLACEHOLDER"
      policy: one_factor
      methods: [GET, POST, PUT, DELETE, OPTIONS, HEAD]
    
    - domain: "TRAEFIK_DOMAIN_PLACEHOLDER"
      policy: one_factor
      methods: [GET, POST]

cookies:
  secure: true
  httponly: true
  samesite: Lax
  domain: "TOP_LEVEL_DOMAIN_PLACEHOLDER"

notifier:
  disable: true

identity_providers:
  oidc:
    enabled: false
AUTHELIA_CONFIG

# Substitute placeholders
sed -i.bak "s|TOP_LEVEL_DOMAIN_PLACEHOLDER|${TOP_LEVEL_DOMAIN}|g" authelia/configuration.yml
sed -i.bak "s|AUTH_DOMAIN_PLACEHOLDER|auth.${TOP_LEVEL_DOMAIN}|g" authelia/configuration.yml
sed -i.bak "s|MUSIC_DOMAIN_PLACEHOLDER|music.${DOMAIN}|g" authelia/configuration.yml
sed -i.bak "s|TRAEFIK_DOMAIN_PLACEHOLDER|traefik.${TOP_LEVEL_DOMAIN}|g" authelia/configuration.yml
rm -f authelia/configuration.yml.bak

log_pass "authelia/configuration.yml generated"

##############################################################################
# 8. GENERATE AUTHELIA USERS DATABASE (if not exists)
##############################################################################

log_info "\nSetting up Authelia users database..."

if [ ! -f authelia/users_database.yml ]; then
  # Generate a default password hash (password: "authelia" - MUST be changed)
  DEFAULT_HASH='$2a$12$e3lGZ8XJwXArv8/VIu2R4edm5g1OikM2nSvR53PocUGyMAK8yToiK'
  
  cat > authelia/users_database.yml << USERS_CONFIG
users:
  admin:
    displayname: Administrator
    password: "${DEFAULT_HASH}"
    email: admin@${TOP_LEVEL_DOMAIN}
    groups:
      - admins
      - users
    totp: ""
USERS_CONFIG
  
  chmod 600 authelia/users_database.yml
  log_warn "users_database.yml created with default admin user"
  log_warn "  Username: admin"
  log_warn "  Password: authelia (CHANGE IMMEDIATELY)"
  log_warn "  Email: admin@${TOP_LEVEL_DOMAIN}"
  log_warn "  To change: docker run --rm authelia/authelia:4.38.5 authelia hash-password"
else
  chmod 600 authelia/users_database.yml
  log_pass "users_database.yml exists"
fi

##############################################################################
# 9. VALIDATE DNS
##############################################################################

log_info "\nValidating DNS configuration..."

if command -v dig &>/dev/null; then
  if dig +short "${DOMAIN}" @8.8.8.8 &>/dev/null; then
    IP=$(dig +short "${DOMAIN}" @8.8.8.8 | head -1)
    log_pass "DNS resolves: ${DOMAIN} → ${IP}"
  else
    log_warn "DNS does not resolve for ${DOMAIN}"
    log_warn "  Add A record: ${DOMAIN} → your-server-ip"
  fi
elif command -v nslookup &>/dev/null; then
  if nslookup "${DOMAIN}" 8.8.8.8 &>/dev/null; then
    log_pass "DNS resolves for ${DOMAIN}"
  else
    log_warn "DNS does not resolve for ${DOMAIN}"
  fi
else
  log_warn "dig/nslookup not available; skipping DNS check"
fi

##############################################################################
# 10. VALIDATE DOCKER-COMPOSE SYNTAX
##############################################################################

log_info "\nValidating docker-compose.yml..."

if docker-compose config > /dev/null 2>&1; then
  log_pass "docker-compose.yml syntax valid"
else
  log_fail "docker-compose.yml has syntax errors"
  docker-compose config
  exit 1
fi

##############################################################################
# 11. VALIDATE PORTS
##############################################################################

log_info "\nChecking port availability..."

check_port() {
  local port=$1
  if nc -z localhost "$port" 2>/dev/null || ss -tln 2>/dev/null | grep -q ":$port " || netstat -tln 2>/dev/null | grep -q ":$port "; then
    return 0  # Port in use
  fi
  return 1  # Port available
}

for port in 80 443 8080; do
  if check_port "$port"; then
    log_warn "Port $port may be in use"
  else
    log_pass "Port $port available"
  fi
done

##############################################################################
# 12. VALIDATE MUSIC LIBRARY
##############################################################################

log_info "\nValidating music library..."

if [ -d "$MUSIC_PATH" ]; then
  COUNT=$(find "$MUSIC_PATH" -type f 2>/dev/null | wc -l)
  if [ "$COUNT" -gt 0 ]; then
    log_pass "Music library: $COUNT files found in $MUSIC_PATH"
  else
    log_warn "Music library empty: $MUSIC_PATH (add music files)"
  fi
else
  log_warn "Music library not found: $MUSIC_PATH"
  mkdir -p "$MUSIC_PATH"
  log_pass "Created directory: $MUSIC_PATH"
fi

if [ -d "$DATA_PATH" ]; then
  log_pass "Data directory ready: $DATA_PATH"
else
  mkdir -p "$DATA_PATH"
  log_pass "Created data directory: $DATA_PATH"
fi

##############################################################################
# 13. VALIDATE FILE PERMISSIONS
##############################################################################

log_info "\nValidating file permissions..."

chmod 600 .env
log_pass ".env permissions set to 600"

chmod 600 authelia/users_database.yml
log_pass "authelia/users_database.yml permissions set to 600"

chmod 600 /srv/traefik/acme.json
log_pass "/srv/traefik/acme.json permissions set to 600"

##############################################################################
# 14. CREATE docker-compose.override.yml for prod
##############################################################################

log_info "\nGenerating docker-compose.override.yml (prod-specific)..."

cat > docker-compose.override.yml << 'OVERRIDE_CONFIG'
version: '3.9'

# Production overrides
# Override resource limits, restart policies, health checks
services:
  traefik:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 512M
        reservations:
          cpus: '1'
          memory: 256M
  
  authelia:
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 256M
        reservations:
          cpus: '0.5'
          memory: 128M
  
  redis:
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 256M
        reservations:
          cpus: '0.5'
          memory: 128M
  
  navidrome:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 512M
        reservations:
          cpus: '1'
          memory: 256M
  
  home-assistant:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 512M
        reservations:
          cpus: '1'
          memory: 256M
OVERRIDE_CONFIG

log_pass "docker-compose.override.yml created"

##############################################################################
# SUMMARY
##############################################################################

echo -e "\n${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                   INITIALIZATION COMPLETE                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"

echo -e "\n${BLUE}Configuration Summary:${NC}"
echo "  Domain:                ${DOMAIN}"
echo "  Top-level domain:      ${TOP_LEVEL_DOMAIN}"
echo "  Auth domain:           auth.${TOP_LEVEL_DOMAIN}"
echo "  Music library:         ${MUSIC_PATH}"
echo "  Data directory:        ${DATA_PATH}"
echo "  Email (Let's Encrypt): ${LETSENCRYPT_EMAIL}"

echo -e "\n${BLUE}Next Steps:${NC}"
echo "  1. Verify .env is correct: cat .env"
echo "  2. Add admin password: docker run --rm authelia/authelia:4.38.5 authelia hash-password"
echo "  3. Update authelia/users_database.yml with admin password hash"
echo "  4. Deploy: docker compose up -d"
echo "  5. Monitor: docker compose logs -f"

echo -e "\n${BLUE}Access Services:${NC}"
echo "  Navidrome:  https://music.${DOMAIN}"
echo "  Dashboard:  https://traefik.${TOP_LEVEL_DOMAIN}/dashboard/"
echo "  Auth:       https://auth.${TOP_LEVEL_DOMAIN}"

echo -e "\n${GREEN}Ready to deploy!${NC}\n"
