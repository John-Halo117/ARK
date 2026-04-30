#!/usr/bin/env bash
set -euo pipefail
source scripts/ci/lib.sh

COMMIT="$1"
STATE_FILE="$STATE_DIR/promoted.json"

python3 - <<EOF
import json,datetime
rec={"commit":"$COMMIT","state":"promoted","timestamp":datetime.datetime.utcnow().isoformat()}
open("$STATE_FILE","w").write(json.dumps(rec))
EOF

log "promoted $COMMIT"
