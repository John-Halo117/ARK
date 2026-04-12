#!/bin/bash
# Hardening checklist and deployment guide for ARK stack

# 1. BEFORE DEPLOYING THE HARDENED VERSION:

# Generate secure passwords
echo "=== Generating secure passwords ==="
MONGO_ROOT_PW=$(openssl rand -base64 32)
MONGO_APP_PW=$(openssl rand -base64 32)
echo "MongoDB Root Password: $MONGO_ROOT_PW"
echo "MongoDB App Password: $MONGO_APP_PW"
echo "Store these in a secrets manager (Vault, pass, bitwarden, etc.)"

# 2. UPGRADE PATH (non-destructive):
# Keep your current docker-compose.yml as backup
# Test the hardened version first:
docker compose -f docker-compose.hardened.yml pull
docker compose -f docker-compose.hardened.yml up -d

# 3. VERIFY HEALTH:
docker ps --format "{{.Names}}\t{{.Status}}"
docker compose -f docker-compose.hardened.yml ps
docker compose -f docker-compose.hardened.yml logs -f

# 4. MONITOR RESOURCE USAGE:
watch -n 1 'docker stats --no-stream'

# 5. BACKUP YOUR DATA BEFORE MIGRATION:
# Named volumes can be backed up:
docker run --rm -v jellyfin-config:/data -v $(pwd)/backups:/backup \
  alpine tar czf /backup/jellyfin-config-$(date +%s).tar.gz -C /data .

docker run --rm -v homeassistant-config:/data -v $(pwd)/backups:/backup \
  alpine tar czf /backup/homeassistant-config-$(date +%s).tar.gz -C /data .

docker run --rm -v unifi-db:/data -v $(pwd)/backups:/backup \
  alpine tar czf /backup/unifi-db-$(date +%s).tar.gz -C /data .

# 6. PRODUCTION ADDITIONS (recommended):

# A. Log Aggregation - add to docker-compose.hardened.yml:
# ```
# loki:
#   image: grafana/loki:latest
#   volumes:
#     - loki-storage:/loki
#   # Configure to aggregate logs from all containers
# ```

# B. Monitoring & Alerting - add to docker-compose.hardened.yml:
# ```
# alertmanager:
#   image: prom/alertmanager:latest
#   volumes:
#     - ./monitoring/alertmanager.yml:/etc/alertmanager/config.yml
#   # Alert on: OOM, restart loops, disk full, high load
# ```

# C. Automated Backups (cron-based):
# Add to crontab:
# 0 2 * * * /path/to/backup-script.sh  # Daily at 2 AM

# D. Health Check Dashboard:
# Use your existing Grafana to create dashboards for:
# - Container CPU/Memory usage
# - Restart frequency
# - Disk I/O and space
# - Network bandwidth

# 7. VOLUME MANAGEMENT:
# List all volumes:
docker volume ls

# Inspect volume:
docker volume inspect jellyfin-config

# 8. GRACEFUL SHUTDOWN:
# The hardened version includes stop_grace_period for UniFi
# This gives it 30s to flush database before kill -9
docker compose -f docker-compose.hardened.yml down
# Wait for graceful shutdown...

# 9. COMPARISON:
# Current risks → Fixes:
# 1. No memory limits → Added CPU/memory limits per container
# 2. :latest tags → Pinned specific versions
# 3. No healthchecks → Added healthchecks to HA, Jellyfin, Mongo
# 4. No restart limits → Added on-failure:5 to stop restart loops
# 5. Unbounded logs → Added json-file driver with max-size/max-file
# 6. No swap prevention → Using deploy.resources instead of old mem_limit
# 7. Bind mounts → Switched to named volumes for durability
# 8. Shared /media → Made read-only, split Jellyfin transcode
# 9. No graceful shutdown → Added stop_grace_period
# 10. No journaling on MongoDB → Added --journal flag
# 11. Password in plaintext → .env.hardened with warnings

# 10. TESTING IMPROVEMENTS:
# Test OOM handling:
docker run --memory=100m --memory-swap=100m alpine sleep 300
# Should be killed gracefully, not crash entire host

# Test restart limit:
docker run --restart=on-failure:2 alpine false
# Should fail 2 times then stop

# Test healthcheck:
docker compose -f docker-compose.hardened.yml ps
# Should show "(healthy)" or "(starting)" status

echo "=== Hardening checklist complete ==="
