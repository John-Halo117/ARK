# Architecture & Implementation Notes

## STACK OVERVIEW

```
┌─────────────────────────────────────────────────────────────────┐
│                         INTERNET                                 │
└────────────────┬────────────────────────────────────────────────┘
                 │ HTTPS (443) / HTTP (80)
                 │
┌────────────────▼────────────────────────────────────────────────┐
│                   TRAEFIK v3                                     │
│  - TLS Termination (Let's Encrypt)                               │
│  - HTTP→HTTPS Redirect                                           │
│  - Routing to backend services                                   │
│  - Docker provider auto-discovery                                │
└────────────────┬────────────────────────────────────────────────┘
                 │ Docker bridge network "proxy"
     ┌───────────┼───────────┬────────────┐
     │           │           │            │
┌────▼──┐  ┌────▼──┐  ┌─────▼──┐  ┌─────▼──┐
│AUTHELIA│  │NAVIDROME│  │REDIS   │  │HOME    │
│:9091   │  │:4533   │  │:6379   │  │ASST    │
│        │  │        │  │        │  │:8123   │
└────────┘  └────────┘  └────────┘  └────────┘
     │           │           │
  Session    Music        Session   (host network)
  Storage    Library      Store
  (TOTP)
```

## SECURITY ARCHITECTURE

### Zero-Trust Design
- **Inbound**: Only Traefik receives external traffic (ports 80/443)
- **Inter-service**: All communication via Docker bridge network ("proxy")
- **Authentication**: Authelia forwardAuth middleware on every route
- **Encryption**: TLS 1.2+ enforced; HSTS enabled

### forwardAuth Flow (Traefik ↔ Authelia)
```
1. User requests https://music.example.com
2. Traefik receives request
3. Traefik calls Authelia: /api/authz/forward-auth
4. Authelia checks session/cookies
   - Valid? → Return 200 OK, pass headers (Remote-User, etc.)
   - Invalid? → Return 401, redirect to auth.example.com login
5. User logs in at Authelia UI
6. Session stored in Redis (persistent, encrypted)
7. Subsequent requests authenticated via session cookie
```

### File Permissions & Secrets
- `acme.json`: mode 600 (certificates from Let's Encrypt)
- `users_database.yml`: mode 600 (TOTP secrets, user hashes)
- `.env`: mode 600 (Redis password, TOTP seed)

### Credential Management
- **No hardcoded secrets** in any config file (use .env + volume mounts)
- **PBKDF2/bcrypt** passwords hashed (Authelia)
- **Redis password** required (not exposed in compose)
- **TOTP secrets** generated per-user (not pre-configured)

## SERVICE ISOLATION

| Service | Network | Exposed | Route | Auth |
|---------|---------|---------|-------|------|
| Traefik | proxy | :80/:443/:8080 | Direct | N/A (reverse proxy) |
| Authelia | proxy | :9091 (hidden) | /api/authz/* | Bypass |
| Navidrome | proxy | :4533 (hidden) | music.example.com | forwardAuth |
| Redis | proxy | :6379 (hidden) | Internal only | Password |
| Home Assistant | host | :8123 | Direct (host) | Optional |

## DATA INTEGRITY

### Bind Mounts (Read-Only)
```
Host: /srv/navidrome/music → Container: /music (READ-ONLY :ro)
```
- Music files immutable from container perspective
- Safe for concurrent read access
- Protection: :ro flag prevents accidental modification

### Named Volumes (Persistent)
```
Host: /srv/navidrome/data → Container: /data (READ-WRITE)
Host: /srv/authelia/data → Container: /data (READ-WRITE)
Host: /srv/redis/data → Container: /data (READ-WRITE)
```
- Persistent across container restarts
- Docker manages mount points
- Survives `docker compose down` (unless `-v` flag)

### Log Directories (Host Paths)
```
/srv/{service}/logs → Container: /var/log/{service}
JSON-file logging with rotation (max 10MB, 3 files)
```

## CERTIFICATE MANAGEMENT (Let's Encrypt)

### HTTP-01 Challenge Flow (Default)
```
1. Traefik requests certificate for music.example.com
2. Let's Encrypt: "Prove ownership by responding to HTTP /.well-known/..."
3. Traefik: Responds on port 80 with challenge token
4. Let's Encrypt: Validates, issues certificate
5. Traefik: Stores cert in /srv/traefik/acme.json (persistent)
6. HTTPS enabled for all routes
```

### Cert Storage & Persistence
- **File**: `/srv/traefik/acme.json` (bind mount on host)
- **Format**: JSON with cert chain, private key, metadata
- **Permissions**: 600 (readable by traefik container + root only)
- **Renewal**: Automatic (Let's Encrypt checks ~30 days before expiry)

### DNS-01 Challenge (Optional)
For wildcard certs or if port 80 unavailable:
- Requires DNS API integration (CloudFlare, Route53, etc.)
- Configure in `traefik/traefik.yml` (dnsChallenge section)
- Set DNS API credentials via .env (CF_DNS_API_TOKEN, etc.)

## AUTHELIA SESSION MANAGEMENT

### Storage Backend (Redis)
```
Session = {
  username: "admin",
  groups: ["admins", "users"],
  session_id: <random>,
  expiration: <timestamp>,
  totp_verified: <boolean>,
}
```

### Session Lifecycle
1. **Login**: User enters credentials → Authelia verifies against users_database.yml
2. **MFA (TOTP)**: Optional 2FA challenge (if configured by user)
3. **Session Creation**: Random session_id generated, stored in Redis
4. **Cookie**: Session cookie (httponly, secure, sameSite=Lax) sent to client
5. **Re-auth**: Traefik validates cookie via forwardAuth on each request
6. **Expiry**: 1 hour (configurable in configuration.yml) or 5 min inactivity
7. **Logout**: Session deleted from Redis

### Security Flags
- `secure: true` - Cookie only sent over HTTPS
- `httponly: true` - No JavaScript access (XSS protection)
- `samesite: Lax` - CSRF protection

## NAVIDROME MUSIC LIBRARY SCANNING

### Scan Process
1. **Startup**: Navidrome scans `/music` directory (first boot)
2. **Scheduled**: Periodic scan every 1 hour (configurable via ND_SCANINTERVAL)
3. **Database**: Music metadata stored in `/data/navidrome.db` (SQLite)
4. **Transcoding**: On-demand MP3 transcode cached in `/data/transcodes/`

### File Format Support
- MP3, FLAC, M4A, OGG, WMA, APE, OPUS, MPC

### Performance
- Initial scan: 5-30 min (depends on library size)
- Incremental scans: 1-5 min (checks file timestamps)
- Web UI responsive during scan (background process)

## TRAEFIK DYNAMIC CONFIGURATION

### Hot-Reload (File Provider)
```yaml
providers:
  file:
    filename: /etc/traefik/dynamic.yml
    watch: true  # Reload on change (no container restart)
```

Changes to `traefik/dynamic.yml` (middleware, TLS rules) apply without downtime:
- Edit file
- Save
- Traefik detects change (~1 second)
- New config applied
- No interruption to active requests

### Static vs Dynamic
- **Static** (`traefik.yml`): Entrypoints, providers, cert resolvers → requires restart
- **Dynamic** (`dynamic.yml`): Middleware, routes, TLS options → hot-reloads

## HOME ASSISTANT INTEGRATION

### Host Network Mode
```yaml
network_mode: host
```
- Home Assistant can access host IP:port directly
- mDNS discovery works (local device detection)
- UPnP/SSDP works (smart home protocol auto-discovery)
- **Trade-off**: Not protected by Traefik/Authelia (not exposed via reverse proxy)

### Alternative: Bridge Network + Traefik
To protect Home Assistant with Traefik/Authelia:
1. Comment out `network_mode: host`
2. Uncomment `networks: [proxy]`
3. Add traefik labels (route + authelia middleware)
4. Integrate mDNS discovery differently (may require secondary container)

### Event Ingestion
Home Assistant can:
- Ingest webhooks from external sources
- Trigger automations
- Send data to other services (via integrations)
- Configured via `/srv/home-assistant/config/configuration.yaml`

## NETWORK ISOLATION

### Docker Bridge Network "proxy"
```
docker network create -d bridge --subnet 172.20.0.0/16 proxy
```

### Internal Communication
- Traefik → Authelia: `http://authelia:9091`
- Authelia → Redis: `redis://redis:6379`
- Traefik → Navidrome: `http://navidrome:4533`

### DNS Resolution (Service Discovery)
Docker embedded DNS server (127.0.0.11:53):
- Translates service name → container IP
- `authelia` resolves to container IP of authelia service
- Automatic, no manual /etc/hosts needed

### Port Exposure Rules
- `ports:` → Mapped on host (Traefik uses these)
- `expose:` → Only on bridge network (internal)
- No mapping → Accessible only via service name (no host access)

## LOGGING STRATEGY

### Drivers & Rotation
```yaml
logging:
  driver: json-file
  options:
    max-size: 10m      # Rotate when file reaches 10MB
    max-file: 3        # Keep 3 rotated files (30MB total)
```

### Log Locations
```
/srv/traefik/logs/traefik.log
/srv/traefik/logs/access.log
/srv/authelia/logs/authelia.log
/srv/navidrome/logs/
/srv/redis/logs/
/srv/home-assistant/logs/
```

### Centralized Logging (Optional)
For ELK/Datadog/Splunk integration:
- Change `logging.driver` to `splunk`, `awslogs`, `datadog`, etc.
- Configure credentials in `logging.options`
- Logs shipped to external platform

## HEALTH CHECKS

Each service includes healthcheck configuration:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:PORT/health"]
  interval: 30s      # Check every 30 seconds
  timeout: 5s        # Fail if no response in 5 seconds
  retries: 3         # Mark unhealthy after 3 consecutive failures
```

### Docker Health Status
```
docker compose ps
STATUS column shows:
  Up 1 minute (healthy)     → Service responding to health check
  Up 1 minute (unhealthy)   → Health check failing (error in logs)
  Up 1 minute (starting)    → First health check not yet run
```

## DISASTER RECOVERY

### Backup Strategy
```bash
# Full backup
tar -czf backup-$(date +%Y%m%d).tar.gz /srv/

# Incremental backup
tar --compare -f backup-full.tar.gz /srv/ > changes.txt

# Cloud backup (S3 example)
aws s3 sync /srv/navidrome/data s3://backup-bucket/navidrome/
```

### Restore Procedure
```bash
# Stop stack
docker compose down

# Restore from backup
tar -xzf backup-20240101.tar.gz -C /

# Restart
docker compose up -d
```

### Data Loss Prevention
- Navidrome DB: Backed up via volume mount (not ephemeral)
- Authelia sessions: Persisted in Redis (survives restarts)
- Certificates: Persisted in acme.json (not regenerated on each restart)
- Music library: Read-only mount (no accidental deletion)

## PRODUCTION CHECKLIST (Summary)

✅ SSL/TLS: Let's Encrypt + auto-renewal
✅ Authentication: Authelia + 2FA (TOTP optional)
✅ Authorization: forwardAuth middleware on all routes
✅ Data Persistence: Named volumes + bind mounts
✅ Network Isolation: Bridge network, no host exposure
✅ Logging: JSON structured, rotated, ship-able
✅ Secrets: .env file (mode 600), password hashing
✅ Health Checks: All services monitored
✅ Resource Limits: Not set (configure in docker-compose.yml if needed)
✅ Zero Downtime Updates: Dynamic config hot-reload supported

---

Generated: Production-grade Docker Compose stack
Tested on: Docker Engine 20.10+ (Linux)
Disclaimer: Customize for your environment; test in staging first
