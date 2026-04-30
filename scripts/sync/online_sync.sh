#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

if [[ ! -f "$SYNC_QUEUE" ]]; then
  echo "no sync queue"
  exit 0
fi

while read -r COMMIT; do
  if [[ -n "$COMMIT" ]]; then
    sync_log "syncing $COMMIT"
    # manual push still controlled by user
    # you can replace this with git push when desired
  fi
done < "$SYNC_QUEUE"

> "$SYNC_QUEUE"
