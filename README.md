# ARK workspace

This workspace now has a clear canonical target: [`ark-core`](ark-core/README.md).
That module holds the control-plane scaffold, the universal ingest-to-truth
architecture docs, the shared Go model layer, and the governance scripts that
tie the repo together.

The preserved [`ark-ssot-mvp`](ark-ssot-mvp/README.md) subtree remains part of
the workspace as the Phase 0 SSOT MVP: Postgres, n8n, Grafana, Ollama, MQTT,
webhooks, and bootstrap SQL. It is kept intact rather than rewritten.

## Canonical docs

The architecture is intentionally split so each concept has one owner:

| File | Owns |
| --- | --- |
| [`ark-core/docs/ARK_TRUTH_SPINE.md`](ark-core/docs/ARK_TRUTH_SPINE.md) | Full ingest-to-truth architecture |
| [`ark-core/docs/CODEX_ARK_SYSTEM_PROMPT.md`](ark-core/docs/CODEX_ARK_SYSTEM_PROMPT.md) | Agent/runtime behavior contract |
| [`ark-core/docs/SYSTEM_MAP.md`](ark-core/docs/SYSTEM_MAP.md) | Compressed system topology |
| [`ark-core/docs/TODO_TIERS.md`](ark-core/docs/TODO_TIERS.md) | S/T/P governance rules |
| [`ark-core/docs/REDTEAM.md`](ark-core/docs/REDTEAM.md) | Red Team gates and scenarios |
| [`ark-core/docs/ark-field-v4.2-foundation.md`](ark-core/docs/ark-field-v4.2-foundation.md) | Current Stage 1 scaffold bridge |

## Layout

| Area | Role |
| --- | --- |
| [`ark-core/`](ark-core/README.md) | Canonical integration target for control plane + truth spine |
| [`ark-core/internal/models/`](ark-core/internal/models/) | Shared event, stability, and ingest-to-truth model types |
| [`ark-core/internal/epistemic/`](ark-core/internal/epistemic/) | Claim states, conflict groups, resolver, and policy types |
| [`ark-core/scripts/ai/`](ark-core/scripts/ai/) | Agent prompt + offline orchestration scaffold |
| [`ark-core/scripts/ci/`](ark-core/scripts/ci/) | Tier enforcement + Red Team gates |
| [`ark-core/config/tiering_rules.json`](ark-core/config/tiering_rules.json) | Canonical S/T/P policy configuration |
| [`ark-ssot-mvp/`](ark-ssot-mvp/README.md) | Preserved SSOT MVP subtree |

## Verify

From [`ark-core/`](ark-core/README.md):

```powershell
.\scripts\verify.ps1
go test ./...
docker compose -f compose.yaml config
docker compose -f docker-compose.yml config
```

## Merge rule

This workspace now prefers cross-links over repeated prose. If a concept already
has a canonical file, add a reference to that file instead of creating a second
version of the same explanation.
