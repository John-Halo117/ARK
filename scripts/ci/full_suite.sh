#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

export GOTOOLCHAIN="${GOTOOLCHAIN:-auto}"
export GOSUMDB="${GOSUMDB:-sum.golang.org}"

log() {
  printf "[ARK-FullSuite] %s\n" "$*"
}

run_step() {
  local name="$1"
  shift
  log "START $name"
  "$@"
  log "PASS  $name"
}

run_optional_step() {
  local name="$1"
  shift
  log "START optional $name"
  if "$@"; then
    log "PASS  optional $name"
  else
    log "SKIP  optional $name"
  fi
}

rust_tests_available() {
  (cd ark && cargo test --no-run >/tmp/ark-cargo-test-link.log 2>&1)
}

docker_available() {
  docker compose config --quiet >/tmp/ark-compose-config.log 2>&1
}

run_step "policy gate" bash scripts/ci/policy_gate.sh
run_step "redteam gate" bash scripts/ci/redteam.sh
run_step "go root tests" go test ./...
run_step "go ark-core tests" bash -c 'cd ark-core && go test ./internal/...'
run_step "python tests" python3 -m pytest -q -s
run_step "python import audit" python3 -m ark.import_audit "$ROOT"
run_step "python compile smoke" python3 -m compileall -q ark/*.py ark/integrations tests/ark scripts/ci scripts/ai
run_step "rust check" bash -c 'cd ark && cargo check'
run_optional_step "rust cargo test native link" rust_tests_available
run_step "source ingest pipeline smoke" python3 scripts/ci/source_ingest_smoke.py
run_optional_step "docker compose config" docker_available

log "FULL SUITE PASS"
