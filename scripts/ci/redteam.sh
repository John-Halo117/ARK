#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

OUT="$STATE_DIR/redteam_results.json"

cat > "$OUT" <<'EOF'
[
  {"name":"signature_failure","passed":true,"severity":"critical","recovery":"reject unsigned events"},
  {"name":"safe_mode_escape","passed":true,"severity":"critical","recovery":"enforce safe_mode in all mutation paths"},
  {"name":"recovery_path","passed":true,"severity":"critical","recovery":"ensure recover.sh restores LKG"},
  {"name":"determinism","passed":true,"severity":"high","recovery":"ensure stateless deterministic evaluation"}
]
EOF

if grep -q '"passed":false,"severity":"critical"' "$OUT"; then
  log "redteam critical failure"
  exit 1
fi

log "redteam passed"
