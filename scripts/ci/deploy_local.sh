#!/usr/bin/env bash
set -euo pipefail

if command -v docker >/dev/null 2>&1; then
  docker compose up -d --build ingestion-leader stability-kernel netwatch
fi
