#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

mkdir -p "$STATE_DIR"

if [[ -f "$ROOT/config/ark.env" ]]; then
  cp "$ROOT/config/ark.env" "$STATE_DIR/last_good_env"
  sha256sum "$ROOT/config/ark.env" | awk '{print $1}' > "$STATE_DIR/last_good_config.sha256"
fi

if [[ -f "$ROOT/config/manifest.json" ]]; then
  cp "$ROOT/config/manifest.json" "$STATE_DIR/last_good_manifest.json"
  sha256sum "$ROOT/config/manifest.json" | awk '{print $1}' > "$STATE_DIR/last_good_manifest.sha256"
fi

log "snapshotted last-known-good config"
