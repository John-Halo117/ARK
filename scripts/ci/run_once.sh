#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

COMMIT="$(git rev-parse HEAD)"
log "CI start $COMMIT"

if command -v go >/dev/null 2>&1; then
  go test ./... || { log "go test failed"; exit 1; }
fi

if command -v pytest >/dev/null 2>&1; then
  pytest || { log "pytest failed"; exit 1; }
fi

bash scripts/ci/deploy_local.sh
bash scripts/ci/smoke.sh

log "CI success $COMMIT"
