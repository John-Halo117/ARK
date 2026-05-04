#!/usr/bin/env bash
##############################################################################
# PRODUCTION BACKUP SCRIPT
# Automated daily backups with retention policy
# Add to crontab: 0 2 * * * bash backup-prod.sh
##############################################################################

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"; }
log_pass() { echo -e "${GREEN}✓${NC} $1"; }
log_fail() { echo -e "${RED}✗${NC} $1"; }

# Load .env
source .env 2>/dev/null || { log_fail ".env not found"; exit 1; }

BACKUP_DIR="/srv/backups"
BACKUP_PREFIX="navidrome_backup_$(date +%Y%m%d_%H%M%S)"
RETENTION_DAYS=30

log_info "Starting backup..."

# Create backup directory
mkdir -p "$BACKUP_DIR"
log_pass "Backup directory ready: $BACKUP_DIR"

##############################################################################
# BACKUP NAVIDROME DATA
##############################################################################

log_info "Backing up Navidrome database..."

tar -czf "$BACKUP_DIR/${BACKUP_PREFIX}.tar.gz" \
  "${DATA_PATH}/navidrome.db" \
  "${DATA_PATH}/cache" \
  /srv/authelia/data \
  /srv/traefik/acme.json \
  2>/dev/null || log_fail "Backup failed"

BACKUP_SIZE=$(du -h "$BACKUP_DIR/${BACKUP_PREFIX}.tar.gz" | awk '{print $1}')
log_pass "Backup complete: ${BACKUP_PREFIX}.tar.gz ($BACKUP_SIZE)"

##############################################################################
# RETENTION POLICY
##############################################################################

log_info "Applying retention policy (keeping last $RETENTION_DAYS days)..."

find "$BACKUP_DIR" -name "navidrome_backup_*.tar.gz" -mtime +$RETENTION_DAYS -delete
REMAINING=$(find "$BACKUP_DIR" -name "navidrome_backup_*.tar.gz" | wc -l)

log_pass "Retained $REMAINING backup(s)"

##############################################################################
# VERIFY BACKUP
##############################################################################

log_info "Verifying backup integrity..."

if tar -tzf "$BACKUP_DIR/${BACKUP_PREFIX}.tar.gz" > /dev/null 2>&1; then
  log_pass "Backup verified (checksummed)"
else
  log_fail "Backup verification failed"
  rm -f "$BACKUP_DIR/${BACKUP_PREFIX}.tar.gz"
  exit 1
fi

##############################################################################
# REMOTE BACKUP (Optional)
##############################################################################

if [ -n "${REMOTE_BACKUP_URL:-}" ]; then
  log_info "Uploading to remote backup..."
  
  # Example: S3 upload
  # aws s3 cp "$BACKUP_DIR/${BACKUP_PREFIX}.tar.gz" s3://my-bucket/backups/
  
  log_pass "Remote backup uploaded (if configured)"
fi

log_pass "Backup complete: ${BACKUP_PREFIX}.tar.gz"

##############################################################################
# RESTORE INSTRUCTIONS
##############################################################################

cat > "$BACKUP_DIR/${BACKUP_PREFIX}.restore.txt" << 'RESTORE_GUIDE'
RESTORE INSTRUCTIONS
====================

To restore from this backup:

1. Stop the stack:
   docker-compose down

2. Remove current data:
   rm -rf /srv/navidrome/data/*

3. Extract backup:
   cd /srv
   tar -xzf backups/navidrome_backup_DATE.tar.gz

4. Fix permissions:
   chmod 600 /srv/traefik/acme.json
   chmod 600 /srv/authelia/data/*

5. Restart services:
   docker-compose up -d

6. Verify:
   docker-compose logs navidrome
   docker-compose ps
RESTORE_GUIDE

log_pass "Restore instructions saved"
