#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

WT_PATH="$1"

if [[ -z "$WT_PATH" ]]; then
  echo "missing worktree path"
  exit 1
fi

log "Deploying from $WT_PATH"

if command -v docker >/dev/null 2>&1; then
  (cd "$WT_PATH" && docker compose up -d --build ingestion-leader stability-kernel netwatch) || {
    log "deploy failed, attempting rollback"
    LKG="$(last_good_commit)"
    if [[ -n "$LKG" ]]; then
      LKG_PATH="$(ensure_worktree "$LKG")"
      (cd "$LKG_PATH" && docker compose up -d --build ingestion-leader stability-kernel netwatch)
      log "rolled back to $LKG"
    fi
    exit 1
  }
fi
