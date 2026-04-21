# ARK core

`ark-core` is the canonical integration target for ARK's control plane and
truth spine. It keeps the current Git-first foundation scaffold, the shared Go
types, and the canonical architecture/governance docs in one place.

## Canonical docs

These files intentionally split ownership so we do not repeat the same concept
in multiple places:

| File | Owns |
| --- | --- |
| `docs/ARK_TRUTH_SPINE.md` | Full ingest-to-truth architecture |
| `docs/CODEX_ARK_SYSTEM_PROMPT.md` | Agent behavior and runtime rules |
| `docs/SYSTEM_MAP.md` | Compressed topology and control roles |
| `docs/TODO_TIERS.md` | S/T/P governance |
| `docs/REDTEAM.md` | Red Team gates and scenarios |
| `docs/ark-field-v4.2-foundation.md` | Current scaffold and implementation bridge |

## Layout

| Area | Role |
| --- | --- |
| `compose.yaml` | Legacy merged platform/event backbone Compose |
| `docker-compose.yml` | ARK-Field v4.2 Stage 1 stack |
| `cmd/` | Go service entrypoints for Ingestion Leader, Stability Kernel, and NetWatch |
| `internal/models/` | Shared event, stability, and ingest-to-truth model types |
| `internal/epistemic/` | Claim states, conflict groups, resolver, and policy types |
| `scripts/ai/` | Agent prompt + offline orchestration scaffold |
| `scripts/ci/` | Tier enforcement + Red Team gates |
| `config/tiering_rules.json` | Canonical machine-readable S/T/P policy |
| `.githooks/post-commit` | Git commit hand-off stub into the Ingestion Leader |

## Verify

From this directory:

```powershell
.\scripts\verify.ps1
go test ./...
docker compose -f compose.yaml config
docker compose -f docker-compose.yml config
```

## Workspace note

The preserved SSOT MVP subtree still lives in the broader workspace next to
`ark-core`. This module does not overwrite it; it provides the canonical
control-plane and truth-spine layer that future integrations can target.
