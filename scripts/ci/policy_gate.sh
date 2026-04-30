#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

[ -f policy/ark_identity_rules.json ] || { echo "missing identity rules"; exit 1; }
[ -f policy/import_registry.json ] || { echo "missing import registry"; exit 1; }

python3 -m ark.import_audit "$ROOT" >/tmp/ark_import_audit.json || {
  cat /tmp/ark_import_audit.json
  exit 1
}

# enforce loop presence
for stage in sense compress judge act verify remember; do
  if ! grep -R "$stage" internal >/dev/null 2>&1; then
    echo "missing core loop stage: $stage"
    exit 1
  fi
done

echo "identity loop enforced"
