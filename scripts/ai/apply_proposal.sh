#!/usr/bin/env bash
set -euo pipefail

PATCH="$1"

if [[ ! -f "$PATCH" ]]; then
  echo "patch not found"
  exit 1
fi

git apply --3way "$PATCH"
echo "[ARK-AI] patch applied"
