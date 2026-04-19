#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

log "CI loop started"

while true; do
  if [[ -f "$QUEUE" ]]; then
    COMMIT="$(head -n1 "$QUEUE")"
    tail -n +2 "$QUEUE" > "$QUEUE.tmp" && mv "$QUEUE.tmp" "$QUEUE"
    if acquire_lock; then
      log "Processing $COMMIT"
      git checkout "$COMMIT"
      if bash scripts/ci/run_once.sh; then
        log "PASS $COMMIT"
      else
        log "FAIL $COMMIT"
      fi
    fi
  fi
  sleep 1
done
