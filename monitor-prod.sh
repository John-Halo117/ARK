#!/usr/bin/env bash
##############################################################################
# PRODUCTION MONITORING & VALIDATION
# Continuous health checks, log monitoring, alert on failures
##############################################################################

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"; }
log_pass() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_fail() { echo -e "${RED}✗${NC} $1"; }

##############################################################################
# HEALTH CHECKS
##############################################################################

check_services() {
  log_info "Checking service status..."
  
  local issues=0
  
  for service in traefik redis authelia navidrome home-assistant; do
    if docker-compose ps "$service" 2>/dev/null | grep -q "Up"; then
      STATUS=$(docker-compose ps "$service" 2>/dev/null | tail -1 | awk '{print $(NF-1), $NF}')
      
      if [[ "$STATUS" == *"healthy"* ]]; then
        log_pass "$service: HEALTHY"
      elif [[ "$STATUS" == *"Up"* ]]; then
        log_warn "$service: RUNNING (health pending)"
      else
        log_fail "$service: UNHEALTHY - $STATUS"
        issues=$((issues + 1))
      fi
    else
      log_fail "$service: NOT RUNNING"
      issues=$((issues + 1))
    fi
  done
  
  return $issues
}

##############################################################################
# CERTIFICATE VALIDATION
##############################################################################

check_certificates() {
  log_info "Checking Let's Encrypt certificates..."
  
  if [ -f /srv/traefik/acme.json ]; then
    CERT_COUNT=$(grep -c '"domain"' /srv/traefik/acme.json 2>/dev/null || echo "0")
    if [ "$CERT_COUNT" -gt 0 ]; then
      # Check for valid certificates (expiry > today)
      EXPIRY=$(openssl x509 -in <(docker run --rm -v /srv/traefik/acme.json:/acme.json traefik:v3.0 cat /acme.json 2>/dev/null) -noout -enddate 2>/dev/null || echo "unknown")
      log_pass "Certificates valid: $EXPIRY"
    else
      log_warn "No certificates in acme.json"
    fi
  else
    log_warn "acme.json not found"
  fi
}

##############################################################################
# DISK SPACE VALIDATION
##############################################################################

check_disk_space() {
  log_info "Checking disk space..."
  
  local threshold=80
  local usage=$(df /srv | tail -1 | awk '{print $(NF-1)}' | sed 's/%//')
  
  if [ "$usage" -gt $threshold ]; then
    log_fail "Disk usage high: ${usage}%"
    return 1
  else
    log_pass "Disk usage: ${usage}%"
    return 0
  fi
}

##############################################################################
# ENDPOINT TESTING
##############################################################################

check_endpoints() {
  log_info "Testing service endpoints..."
  
  # Load domain from .env
  source .env 2>/dev/null || true
  
  # Traefik dashboard
  if timeout 5 curl -s -k "https://traefik.${TOP_LEVEL_DOMAIN}" 2>/dev/null | grep -q "Traefik\|dashboard"; then
    log_pass "Traefik dashboard accessible"
  else
    log_warn "Traefik dashboard not responding (SSL error or not ready)"
  fi
  
  # Authelia health
  if timeout 5 curl -s "http://authelia:9091/api/health" 2>/dev/null | grep -q "ok"; then
    log_pass "Authelia health endpoint responding"
  else
    log_warn "Authelia health endpoint not responding"
  fi
  
  # Navidrome health
  if timeout 5 curl -s "http://navidrome:4533/health" 2>/dev/null | grep -q "ok"; then
    log_pass "Navidrome health endpoint responding"
  else
    log_warn "Navidrome health endpoint not responding"
  fi
}

##############################################################################
# LOG ANALYSIS
##############################################################################

check_logs() {
  log_info "Analyzing recent logs for errors..."
  
  for service in traefik authelia navidrome; do
    ERROR_COUNT=$(docker-compose logs "$service" --tail 100 2>/dev/null | grep -i "error\|failed\|fatal" | wc -l || echo "0")
    
    if [ "$ERROR_COUNT" -gt 0 ]; then
      log_warn "$service: $ERROR_COUNT errors in last 100 lines"
    else
      log_pass "$service: no recent errors"
    fi
  done
}

##############################################################################
# DATABASE VALIDATION
##############################################################################

check_databases() {
  log_info "Checking database health..."
  
  # Redis
  if docker-compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" ping 2>/dev/null | grep -q "PONG"; then
    log_pass "Redis responding"
  else
    log_fail "Redis not responding"
  fi
  
  # Navidrome DB
  if [ -f "${DATA_PATH}/navidrome.db" ]; then
    SIZE=$(du -h "${DATA_PATH}/navidrome.db" | awk '{print $1}')
    log_pass "Navidrome database: $SIZE"
  else
    log_warn "Navidrome database not found"
  fi
}

##############################################################################
# BACKUP VERIFICATION
##############################################################################

check_backups() {
  log_info "Checking backup status..."
  
  BACKUP_DIR="/srv/backups"
  if [ ! -d "$BACKUP_DIR" ]; then
    log_warn "No backup directory found at $BACKUP_DIR"
    log_info "  Create with: mkdir -p $BACKUP_DIR"
    return
  fi
  
  LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/*.tar.gz 2>/dev/null | head -1 || true)
  if [ -z "$LATEST_BACKUP" ]; then
    log_warn "No backups found in $BACKUP_DIR"
  else
    BACKUP_AGE=$(date -d "$(stat -c %y "$LATEST_BACKUP" | cut -d' ' -f1)" +%s 2>/dev/null || echo "0")
    NOW=$(date +%s)
    DAYS_OLD=$(( (NOW - BACKUP_AGE) / 86400 ))
    
    if [ "$DAYS_OLD" -lt 7 ]; then
      log_pass "Latest backup: $DAYS_OLD days old ($(basename "$LATEST_BACKUP"))"
    else
      log_warn "Latest backup: $DAYS_OLD days old (consider new backup)"
    fi
  fi
}

##############################################################################
# MAIN MONITORING LOOP
##############################################################################

if [ "${1:-}" = "monitor" ]; then
  # Continuous monitoring
  echo -e "${GREEN}Starting continuous monitoring (Ctrl+C to stop)${NC}\n"
  
  while true; do
    clear
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║          PRODUCTION STACK HEALTH MONITORING                  ║${NC}"
    echo -e "${GREEN}║          $(date +'%Y-%m-%d %H:%M:%S')${BLUE}                                              ${GREEN}║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}\n"
    
    check_services || true
    echo ""
    check_endpoints || true
    echo ""
    check_disk_space || true
    echo ""
    check_logs || true
    echo ""
    check_databases || true
    echo ""
    check_certificates || true
    echo ""
    check_backups || true
    
    echo -e "\n${BLUE}Next check in 60 seconds...${NC}"
    sleep 60
  done
else
  # Single check
  echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║          PRODUCTION STACK HEALTH CHECK                       ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}\n"
  
  check_services || true
  echo ""
  check_endpoints || true
  echo ""
  check_disk_space || true
  echo ""
  check_logs || true
  echo ""
  check_databases || true
  echo ""
  check_certificates || true
  echo ""
  check_backups || true
  
  echo -e "\n${BLUE}To monitor continuously: bash monitor-prod.sh monitor${NC}\n"
fi
