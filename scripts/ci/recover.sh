#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

log "=== ARK RECOVERY START ==="

# Enable safe mode flags
export ARK_SAFE_MODE=1
export ARK_AUTONOMY_ENABLED=0
export ARK_EXTERNAL_ENABLED=0

log "safe mode enabled"

# Restore last-known-good config
if [[ -f "$STATE_DIR/last_good_env" ]]; then
  cp "$STATE_DIR/last_good_env" "$ROOT/config/ark.env"
  log "restored ark.env"
fi

if [[ -f "$STATE_DIR/last_good_manifest.json" ]]; then
  cp "$STATE_DIR/last_good_manifest.json" "$ROOT/config/manifest.json"
  log "restored manifest"
fi

# Restore last-known-good commit
LKG=$(last_good_commit || true)
if [[ -n "$LKG" ]]; then
  git checkout "$LKG"
  log "rolled back to last good commit $LKG"
fi

# Restart services (best effort)
if command -v docker >/dev/null 2>&1; then
  docker compose down || true
  docker compose --env-file config/ark.env up -d --build
  log "services restarted"
fi

# Health check
sleep 3
curl -s http://localhost:8082/health || log "health check failed"

log "=== ARK RECOVERY COMPLETE ==="
