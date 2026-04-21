#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

require_file() {
  local file="$1"
  if [[ ! -f "$ROOT/$file" ]]; then
    echo "missing required file: $file" >&2
    exit 1
  fi
}

require_text() {
  local file="$1"
  local text="$2"
  if ! grep -Fq "$text" "$ROOT/$file"; then
    echo "missing required text '$text' in $file" >&2
    exit 1
  fi
}

require_file "docs/ARK_TRUTH_SPINE.md"
require_file "docs/CODEX_ARK_SYSTEM_PROMPT.md"
require_file "docs/REDTEAM.md"
require_file "docs/TODO_TIERS.md"
require_file "config/tiering_rules.json"

require_text "docs/CODEX_ARK_SYSTEM_PROMPT.md" "only SSOT is actionable truth"
require_text "docs/CODEX_ARK_SYSTEM_PROMPT.md" "recover()"
require_text "docs/ARK_TRUTH_SPINE.md" "graph may contain contradictions"
require_text "docs/ARK_TRUTH_SPINE.md" "All math-layer outputs are derived values, never raw truth."
require_text "docs/REDTEAM.md" "signature failure"
require_text "docs/REDTEAM.md" "audit corruption"
require_text "docs/REDTEAM.md" "safe mode escape"
require_text "docs/REDTEAM.md" "replay inconsistency"
require_text "docs/REDTEAM.md" "resource exhaustion"

echo "redteam gate passed"
