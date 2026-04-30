# ARK Red Team

`REDTEAM.md` is the canonical adversarial-enforcement source. It defines what
must be tested before trust or promotion claims are accepted.

The higher-level operating posture lives in `docs/MISSION_GRADE_RULES.md`.
Machine-readable invariants live in `config/system_invariants.json`.

## Core rule

No trust claim is valid unless Red Team fails to break it.

If Red Team fails:

- block promotion
- keep or force SAFE mode when relevant
- surface the failing scenario and invariant

## Scenario tiers

Tier 1: contract checks that must always pass.

- required docs and gates exist
- truth-boundary language is present
- recovery and tier rules are present

Tier 2: promotion blockers that must pass before shipping automation.

- signature failure
- audit corruption
- safe mode escape
- replay inconsistency
- resource exhaustion
- conflict injection
- false consensus
- adversarial source

Tier 3: stress/chaos scenarios.

- long-run replay pressure
- sustained noisy source mixes
- repeated rebuild/reparse cycles

## Current gate

Until full runtime scenarios exist, the repo gate should at least verify:

- canonical docs exist
- the system prompt encodes the truth boundary
- the tier rules file is valid
- the Red Team scenarios are listed

## Planned runtime stubs

Future scenario stubs should live under:

```text
internal/redteam/scenarios/
  conflict_injection.go
  false_consensus.go
  adversarial_source.go
```

These remain next-phase work until the runtime surfaces are ready.
