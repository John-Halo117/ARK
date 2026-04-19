#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

COMMIT="$1"
WT="$(ensure_worktree "$COMMIT")"

log "CI start $COMMIT (worktree: $WT)"

pushd "$WT" >/dev/null

bash scripts/ci/policy_gate.sh || { write_result "$COMMIT" "fail" "policy_gate"; exit 1; }

if command -v go >/dev/null 2>&1; then
  go test ./... || { write_result "$COMMIT" "fail" "go test"; exit 1; }
fi

if command -v pytest >/dev/null 2>&1; then
  pytest || { write_result "$COMMIT" "fail" "pytest"; exit 1; }
fi

popd >/dev/null

# enforce rolling reliability BEFORE deploy
if ! python3 scripts/ci/reliability_gate.py; then
  write_result "$COMMIT" "fail" "reliability_gate"
  log "CI blocked by 99.9% reliability requirement"
  exit 1
fi

# deploy ONLY if tests + reliability pass
bash scripts/ci/deploy_local.sh "$WT"

# verify
if bash scripts/ci/smoke.sh; then
  write_result "$COMMIT" "pass" "ok"
  mark_last_good "$COMMIT"
  mark_current_deploy "$COMMIT"
  queue_online_sync "$COMMIT"
  log "CI success $COMMIT"
else
  write_result "$COMMIT" "fail" "smoke"
  log "CI smoke failed $COMMIT"
  exit 1
fi

cleanup_worktree "$COMMIT"
