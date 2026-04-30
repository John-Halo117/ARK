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
| `docs/MISSION_GRADE_RULES.md` | Mission posture, central operating rules, and invariants |
| `docs/SYSTEM_MAP.md` | Compressed topology and control roles |
| `docs/TODO_TIERS.md` | S/T/P governance |
| `docs/REDTEAM.md` | Red Team gates and scenarios |
| `docs/ark-field-v4.2-foundation.md` | Current scaffold and implementation bridge |

## Layout

| Area | Role |
| --- | --- |
| `../docker-compose.yml` | Root-level ARK stack used for compose validation |
| `cmd/` | Go service entrypoints for Ingestion Leader, Stability Kernel, and NetWatch |
| `forge/` | Forge self-coding engine with bounded search, redteam, and state persistence |
| `internal/models/` | Shared event, stability, and ingest-to-truth model types |
| `internal/epistemic/` | Claim states, conflict groups, resolver, and policy types |
| `scripts/ai/` | Compatibility entrypoint that delegates self-coding tasks into Forge |
| `scripts/ci/` | Tier enforcement + Red Team gates |
| `config/tiering_rules.json` | Canonical machine-readable S/T/P policy |
| `config/operating_rules.json` | Machine-readable operating rules and control modes |
| `config/system_invariants.json` | Machine-readable mission invariants |
| `.githooks/post-commit` | Git commit hand-off stub into the Ingestion Leader |

## Forge MVP

Forge is the bounded self-coding engine inside `ark-core`. The current MVP can:

- classify a task through the existing tier gate
- accept a task-supplied unified diff or ask Ollama for diff-only proposals
- evaluate candidates in sandboxes with tests, lint, compile checks, and redteam
- persist local Forge state in `.forge/state.json`
- write result and accepted-patch artifacts to `.forge/artifacts/`
- apply an accepted patch back to the target repo with `--apply`
- run a single inline task from the CLI without a batch JSON file
- probe Ollama readiness with `--ollama-check`

Example:

```bash
.venv/bin/python scripts/ai/orchestrator.py --tasks /path/to/tasks.json --apply
```

Ollama-backed one-off run:

```bash
.venv/bin/python scripts/ai/orchestrator.py \
  --task "fix the failing self-coding smoke test" \
  --scope S1 \
  --todo T1 \
  --target-file tests/test_forge_mvp.py \
  --ollama \
  --executor-model qwen2.5-coder:7b \
  --planner-model qwen2.5-coder:14b \
  --redteam-model qwen2.5-coder:7b \
  --apply
```

Check Ollama:

```bash
.venv/bin/python scripts/ai/orchestrator.py --ollama --ollama-check
```

Low-friction launcher:

```bash
../forge --check
../forge
../forge "fix the failing greeting test" greetings.py tests/test_greetings.py
```

If you are working directly inside `ark-core`, the local entrypoint is:

```bash
.venv/bin/python scripts/ai/forge.py "fix the failing greeting test" greetings.py tests/test_greetings.py
```

That launcher:

- defaults to the current working repo
- opens the Forge Textual control panel by default when no task is provided
- auto-detects the WSL-to-Windows Ollama bridge
- auto-selects the best installed coder model
- applies the accepted patch unless you pass `--no-apply`
- keeps planner/redteam model calls off by default for faster local runs

Inside the TUI you get:

- task input plus run/step/stop controls
- a diff inspector with recent-run history
- separate redteam and test panels
- a logs/events stream
- a command palette via `:`

## Verify

From this directory:

```powershell
.\scripts\verify.ps1
go test ./...
docker compose -f ..\docker-compose.yml config
```

## Workspace note

The preserved SSOT MVP subtree still lives in the broader workspace next to
`ark-core`. This module does not overwrite it; it provides the canonical
control-plane and truth-spine layer that future integrations can target.
