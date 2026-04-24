# ARK-Field v4.2 Stage 1 Foundation

This scaffold introduces the minimum repo shape needed for the ARK-Field v4.2
pipeline while preserving the existing root-level deployment stack.

The Stage 1 scaffold now sits under a canonical doc set:

- [`ARK_TRUTH_SPINE.md`](ARK_TRUTH_SPINE.md) owns the full ingest-to-truth architecture.
- [`CODEX_ARK_SYSTEM_PROMPT.md`](CODEX_ARK_SYSTEM_PROMPT.md) owns agent behavior.
- [`MISSION_GRADE_RULES.md`](MISSION_GRADE_RULES.md) owns mission posture, rules, and invariants.
- [`SYSTEM_MAP.md`](SYSTEM_MAP.md) owns the compressed topology.
- [`TODO_TIERS.md`](TODO_TIERS.md) owns S/T/P governance.
- [`REDTEAM.md`](REDTEAM.md) owns adversarial gates.

## Updated Directory Tree

```text
ark-core/
|-- .githooks/
|   `-- post-commit
|-- build/
|   `-- ark-field/
|       `-- Dockerfile
|-- cmd/
|   |-- ingestion-leader/
|   |   `-- main.go
|   |-- netwatch/
|   |   `-- main.go
|   `-- stability-kernel/
|       `-- main.go
|-- config/
|   `-- tiering_rules.json
|-- docs/
|   |-- ARK_TRUTH_SPINE.md
|   |-- CODEX_ARK_SYSTEM_PROMPT.md
|   |-- REDTEAM.md
|   |-- SYSTEM_MAP.md
|   |-- TODO_TIERS.md
|   `-- ark-field-v4.2-foundation.md
|-- internal/
|   |-- epistemic/
|       |-- conflict.go
|       |-- policy.go
|       |-- resolver.go
|   |   `-- states.go
|   `-- models/
|       |-- cid_object.go
|       |-- event.go
|       |-- stability_metrics.go
|       `-- truth_spine.go
|-- scripts/
|   |-- ai/
|   |   |-- codex_prompt.txt
|   |   `-- orchestrator.py
|   `-- ci/
|       |-- enforce_tiers.py
|       `-- redteam.sh
|-- go.mod
`-- tests/
```

## Stage 1 Notes

- The existing root-level [`../docker-compose.yml`](../../docker-compose.yml)
  remains the compose stack validated by CI and the local verify script.
- All new services mount the NAS at `/mnt/nas`, with the CAS root reserved at
  `/mnt/nas/cas`.
- `.githooks/post-commit` is a stub hand-off from Git commits into the
  Ingestion Leader pipeline.
- `internal/models` contains the canonical Stage 1 Go models that Stage 2 will
  use for event normalization and stability evaluation.
- `internal/epistemic` holds the claim-state, conflict, resolver, and policy
  scaffolding that will let the truth spine move from docs into runtime code.
- `scripts/ai` and `scripts/ci` are the repo-level control surfaces for
  orchestration, tier gating, and Red Team validation.

## Stage 1 boundary

This stage intentionally stops at docs, shared types, and verification gates.
It does not yet wire the full truth spine into Postgres schemas, runtime
endpoints, signed envelopes, or mTLS. Those remain explicit next-phase work in
[`ARK_TRUTH_SPINE.md`](ARK_TRUTH_SPINE.md) and
[`REDTEAM.md`](REDTEAM.md).
