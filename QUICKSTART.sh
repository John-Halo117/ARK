#!/bin/bash
##############################################################################
# QUICK START GUIDE
# Production Stack: Traefik + Authelia + Navidrome + Home Assistant
##############################################################################

# STEP 1: Pre-flight validation
bash ./preflight-checks.sh

# STEP 2: Configure environment
# Edit .env and replace all CHANGE_ME values:
# - DOMAIN (e.g., music.example.com)
# - REDIS_PASSWORD
# - LETSENCRYPT_EMAIL
# - Music library path (MUSIC_PATH)
# - Authelia users/passwords (in authelia/users_database.yml)

# STEP 3: Set correct permissions
chmod 600 .env
chmod 600 authelia/users_database.yml
chmod 600 /srv/traefik/acme.json

# STEP 4: Generate Authelia password hashes
# Run: docker run --rm authelia/authelia:4.38.5 authelia hash-password
# Update authelia/users_database.yml with hashes

# STEP 5: Start the stack
docker compose up -d

# STEP 6: Verify services are healthy
docker compose ps
docker compose logs -f

# STEP 7: Access services
# Navidrome: https://music.example.com (requires Authelia login)
# Traefik dashboard: https://traefik.example.com/dashboard/ (requires Authelia login)
# Home Assistant: http://host:8123 (if using host network)

# STEP 8: Initial Authelia setup
# 1. User logs in with credentials from authelia/users_database.yml
# 2. Click "Settings" → "Two-Factor Authentication" (TOTP) to enable 2FA
# 3. Configure allowed devices/remember this device

##############################################################################
# TROUBLESHOOTING
##############################################################################

# Check service logs
# docker compose logs traefik
# docker compose logs authelia
# docker compose logs navidrome
# docker compose logs home-assistant

# Check container status
# docker compose ps

# Verify Traefik routing
# curl -v https://music.example.com

# Verify Authelia is protecting services
# curl -v -H "Authorization: Bearer token" https://music.example.com

# Reset password (edit users_database.yml)
# docker run --rm authelia/authelia:4.38.5 authelia hash-password
# Update password in users_database.yml
# docker compose restart authelia

# Delete certificates and restart (if Let's Encrypt issues)
# rm /srv/traefik/acme.json
# touch /srv/traefik/acme.json && chmod 600 /srv/traefik/acme.json
# docker compose restart traefik
