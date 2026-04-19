#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
AI_DIR="$ROOT/.ark_ai"
QUEUE="$AI_DIR/queue"

mkdir -p "$AI_DIR"

TASK="$1"
ID="$(date +%s)"

echo "{\"id\":\"$ID\",\"task\":\"$TASK\"}" >> "$QUEUE"

echo "[ARK-AI] queued task $ID"
