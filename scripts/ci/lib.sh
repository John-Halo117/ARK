#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
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

timestamp() {
  date -Is
}

log() {
  printf "[%s] %s\n" "$(timestamp)" "$*" | tee -a "$LOG"
}

sync_log() {
  printf "[%s] %s\n" "$(timestamp)" "$*" | tee -a "$SYNC_LOG"
}

acquire_lock() {
  exec 9>"$LOCK"
  flock -n 9
}

worktree_path() {
  local commit="$1"
  printf "%s/%s" "$WORKTREES_DIR" "$commit"
}

ensure_worktree() {
  local commit="$1"
  local path
  path="$(worktree_path "$commit")"
  if [[ ! -d "$path/.git" && ! -f "$path/.git" ]]; then
    git worktree add --detach "$path" "$commit" >/dev/null 2>&1
  fi
  printf "%s" "$path"
}

cleanup_worktree() {
  local commit="$1"
  local path
  path="$(worktree_path "$commit")"
  if [[ -d "$path" ]]; then
    git worktree remove --force "$path" >/dev/null 2>&1 || rm -rf "$path"
  fi
}

write_result() {
  local commit="$1"
  local status="$2"
  local detail="$3"
  cat > "$RESULTS_DIR/$commit.json" <<EOF
{"commit":"$commit","status":"$status","timestamp":"$(timestamp)","detail":"$detail"}
EOF
}

mark_last_good() {
  local commit="$1"
  printf "%s\n" "$commit" > "$LAST_GOOD_FILE"
}

mark_current_deploy() {
  local commit="$1"
  printf "%s\n" "$commit" > "$CURRENT_DEPLOY_FILE"
}

last_good_commit() {
  [[ -f "$LAST_GOOD_FILE" ]] && cat "$LAST_GOOD_FILE" || true
}

queue_online_sync() {
  local commit="$1"
  printf "%s\n" "$commit" >> "$SYNC_QUEUE"
}
