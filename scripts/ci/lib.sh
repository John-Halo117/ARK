#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
CI_DIR="$ROOT/.ark_ci"
QUEUE="$CI_DIR/queue"
LOCK="$CI_DIR/lock"
LOG="$CI_DIR/ci.log"

mkdir -p "$CI_DIR"

log() {
  printf "[%s] %s\n" "$(date -Is)" "$*" | tee -a "$LOG"
}

acquire_lock() {
  exec 9>"$LOCK"
  flock -n 9
}
