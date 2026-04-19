#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
RESULTS="$ROOT/.ark_ci/results"
AI_DIR="$ROOT/.ark_ai"
QUEUE="$AI_DIR/queue"

mkdir -p "$AI_DIR"

LAST_FAIL=$(grep -l '"status":"fail"' $RESULTS/*.json | tail -n1 || true)

if [[ -z "$LAST_FAIL" ]]; then
  echo "no failure found"
  exit 0
fi

DETAIL=$(cat "$LAST_FAIL")
ID="$(date +%s)"

echo "{\"id\":\"$ID\",\"task\":\"Fix failure: $DETAIL\"}" >> "$QUEUE"

echo "[ARK-AI] queued repair task"
