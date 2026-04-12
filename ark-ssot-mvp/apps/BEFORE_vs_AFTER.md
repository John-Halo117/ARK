# ARK Stack - Before vs After Hardening

## QUICK COMPARISON

### Memory & Resource Management

**BEFORE (Vulnerable)**
```yaml
mem_limit: 512M            # MongoDB - WAY too low
memswap_limit: 512M        # Enables swap (silent slowdown)
# Home Assistant & Jellyfin: NO LIMITS - can crash host
```

**AFTER (Hardened)**
```yaml
deploy:
  resources:
    limits:
      memory: 1.5G         # MongoDB - safe level
      cpus: '2.0'          # CPU throttle for Jellyfin
    reservations:
      memory: 1G           # Guaranteed minimum
      cpus: '1.0'          # Reserved capacity
# All services have explicit limits
```

### Image Versions

**BEFORE (Vulnerable)**
```yaml
image: ghcr.io/home-assistant/home-assistant:stable  # Auto-upgrades
image: lscr.io/linuxserver/jellyfin:latest           # Unknown version
image: mongo:7.0-jammy                                # No patch version
```

**AFTER (Hardened)**
```yaml
image: ghcr.io/home-assistant/home-assistant:2024.4  # Explicit version
image: lscr.io/linuxserver/jellyfin:10.8.13          # Tested & stable
image: mongo:7.0-jammy                                # Same (safe)
image: lscr.io/linuxserver/unifi-network-application:7.5.187
```

### Restart Policy

**BEFORE (Vulnerable)**
```yaml
restart: unless-stopped  # Infinite restarts hide real errors
```

**AFTER (Hardened)**
```yaml
restart: on-failure:5   # Stop after 5 attempts, alert on failure
```

### Healthchecks

**BEFORE (Missing)**
```yaml
healthcheck:  # Only on MongoDB
  test: ["CMD", "mongosh", ...]

# NO healthchecks on HA, Jellyfin, Unifi
```

**AFTER (Complete)**
```yaml
# Home Assistant healthcheck
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8123/api/"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s

# Jellyfin healthcheck
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8096/health"]

# MongoDB healthcheck
healthcheck:
  test: ["CMD", "mongosh", "--quiet", "mongodb://localhost:27017/admin", "--eval", "db.runCommand({ ping: 1 }).ok"]

# UniFi healthcheck
healthcheck:
  test: ["CMD", "curl", "-f", "https://localhost:8443/api/system/information"]
```

### Logging

**BEFORE (Vulnerable)**
```yaml
# No logging config - uses default (unbounded)
# Logs fill /var/lib/docker/containers/ indefinitely
# No rotation = disk fills after days/weeks
```

**AFTER (Hardened)**
```yaml
logging:
  driver: json-file
  options:
    max-size: "100m"      # Rotate at 100MB
    max-file: "3"         # Keep 3 old files (300MB total)
# Applied to ALL services
```

### Volumes

**BEFORE (Vulnerable)**
```yaml
volumes:
  - ./homeassistant/config:/config      # Bind mount, fragile
  - ${ARK_MEDIA_DIR}:/media             # Shared RW between HA & Jellyfin
  - ./jellyfin/config:/config           # Bind mount
```

**AFTER (Hardened)**
```yaml
volumes:
  # Named volumes - durable, backupable
  homeassistant-config:
    driver: local
  jellyfin-config:
    driver: local
  jellyfin-transcode:
    driver: local
  unifi-config:
    driver: local
  unifi-db:
    driver: local

# In compose:
volumes:
  - homeassistant-config:/config
  - ${ARK_MEDIA_DIR}:/media:ro          # Read-only - prevents corruption
  - jellyfin-transcode:/transcode        # Separate volume for temp files
```

### Database (MongoDB)

**BEFORE (Vulnerable)**
```yaml
# No journaling
# 512M memory (gets OOM killed)
# Unclean shutdown = corruption
command:  # Default (no crash recovery)
  - mongod
```

**AFTER (Hardened)**
```yaml
command:
  - mongod
  - --auth
  - --journal  # Enable crash recovery
  
deploy:
  resources:
    limits:
      memory: 1.5G  # Proper buffer size
```

### Graceful Shutdown

**BEFORE (Vulnerable)**
```yaml
# No grace period - UniFi gets SIGKILL immediately
# Data doesn't flush to disk
```

**AFTER (Hardened)**
```yaml
unifi:
  stop_grace_period: 30s  # 30s for UniFi to shutdown cleanly
  # Then SIGKILL if still running
```

### Environment Variables

**BEFORE (Vulnerable)**
```env
UNIFI_MONGO_ROOT_PASSWORD=SecureMongoRoot_$(date +%s)_ChangeThis
UNIFI_MONGO_APP_PASSWORD=SecureUnifiApp_$(date +%s)_ChangeThis
UNIFI_PROTECT_ADMIN_PASSWORD=unifi  # Default password!
```

**AFTER (Hardened)**
```env
# .env.hardened with warnings:
UNIFI_MONGO_ROOT_PASSWORD=CHANGE_ME_Generate_random_with_openssl_rand_base64_32
UNIFI_MONGO_APP_PASSWORD=CHANGE_ME_Generate_random_with_openssl_rand_base64_32
# File includes: "SECURITY: Use strong, random passwords."
```

---

## FAILURE SCENARIOS

### Scenario 1: High Load (Streaming + Automation)

**BEFORE:**
- Jellyfin transcode starts
- No memory limit → grabs 30GB
- OOM killer triggers
- Kills random process → system becomes unresponsive
- Host is unreachable

**AFTER:**
- Jellyfin transcode starts
- Hits 1GB limit → gracefully degrades
- Other services (HA, UniFi) keep working
- Alerts fire (Jellyfin restart count rises)
- User adjusts transcode settings or adds RAM

---

### Scenario 2: Database Corruption

**BEFORE:**
- UniFi database in use
- Container crashes
- Hard kill (no flush) → MongoDB data corrupted
- Weeks of network config lost
- Only recovery: restore from backup (if you have one)

**AFTER:**
- Container crashes
- Gets 30s graceful shutdown → flushes journal
- Journaling enabled → can recover from unclean shutdown
- Healthcheck detects it's down → restart happens
- Data intact on recovery

---

### Scenario 3: Silent Service Failure

**BEFORE:**
- Jellyfin transcode OOM kills
- Container stays "running" in Docker
- Web UI is dead but Docker shows "Up"
- User doesn't know → thinks it's working
- Days of failed transcodes accumulate

**AFTER:**
- Jellyfin crashes
- Healthcheck fails after 3 retries
- Container marked "unhealthy"
- Restart triggered (on-failure)
- Alert visible in monitoring
- User knows immediately

---

### Scenario 4: Disk Fills

**BEFORE:**
- Container logs grow unbounded
- /var/lib/docker/containers fills disk
- System can't write
- Everything crashes (DB, apps, OS)

**AFTER:**
- Logs rotate at 100MB per container
- Max 300MB per service
- Disk space stable
- Old logs auto-deleted

---

## DEPLOYMENT PATH

### Option A: Fresh Start (Recommended)
```bash
docker compose -f docker-compose.hardened.yml up -d
# Wait for healthchecks to pass
docker compose -f docker-compose.hardened.yml ps
```

### Option B: Migrate Existing Data
```bash
# Backup current data
docker run --rm -v homeassistant-config:/data -v $(pwd)/backups:/backup \
  alpine tar czf /backup/homeassistant-config.tar.gz -C /data .

docker run --rm -v unifi-db:/data -v $(pwd)/backups:/backup \
  alpine tar czf /backup/unifi-db.tar.gz -C /data .

# Stop current
docker compose down

# Start new
docker compose -f docker-compose.hardened.yml up -d

# Wait for services to initialize
sleep 30

# Restore if needed
docker compose -f docker-compose.hardened.yml exec unifi-db mongorestore /backups/...
```

---

## MONITORING CHECKLIST

After deploying hardened version, verify:

- [ ] All services show "healthy" in `docker ps`
- [ ] No "restarting" loops (check `docker ps` every 10s)
- [ ] Memory usage stable (no slow growth toward limit)
- [ ] CPU usage < 80% baseline
- [ ] Disk space stable (logs not growing)
- [ ] Logs are properly rotated (check `/var/lib/docker/containers/`)
- [ ] Can access all three UIs: HA, Jellyfin, UniFi
- [ ] Healthchecks fire properly (trigger a fake crash to test)

---

## FILES PROVIDED

1. **docker-compose.hardened.yml** - Production-ready compose file
2. **.env.hardened** - Secure environment template
3. **VULNERABILITY_REPORT.md** - Detailed analysis (this file)
4. **HARDENING_GUIDE.sh** - Setup & backup commands
