#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"

# load central env if present
if [[ -f "$ROOT/config/ark.env" ]]; then
  set -a
  source "$ROOT/config/ark.env"
  set +a
fi

CI_DIR="$ROOT/.ark_ci"
QUEUE="$CI_DIR/queue"
LOCK="$CI_DIR/lock"
LOG="$CI_DIR/ci.log"
RESULTS_DIR="$CI_DIR/results"
WORKTREES_DIR="$CI_DIR/worktrees"
STATE_DIR="$CI_DIR/state"
LAST_GOOD_FILE="$STATE_DIR/last_good_commit"
CURRENT_DEPLOY_FILE="$STATE_DIR/current_deploy_commit"
SYNC_QUEUE="$CI_DIR/sync_queue"
SYNC_LOG="$CI_DIR/sync.log"

mkdir -p "$CI_DIR" "$RESULTS_DIR" "$WORKTREES_DIR" "$STATE_DIR"

# rest unchanged
