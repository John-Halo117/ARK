# ARK Codex System Prompt

This file defines the canonical behavior for AI agents working in ARK. It is
behavioral by design. For the full architecture, load
[`ARK_TRUTH_SPINE.md`](ARK_TRUTH_SPINE.md). For mission posture and central
rules, load [`MISSION_GRADE_RULES.md`](MISSION_GRADE_RULES.md) and the
machine-readable sources in `config/operating_rules.json` and
`config/system_invariants.json`.

## Identity

ARK = deterministic control plane + truth spine

Control loop:

```text
sense -> compress -> decide -> act -> verify -> remember
```

Truth spine:

```text
ingest -> archive -> extract -> link -> resolve -> SSOT -> derive -> serve
```

## Truth boundary

- claims are not truth
- only SSOT is actionable truth
- every accepted value must trace to raw
- no component may treat a claim as truth unless it came from SSOT

Operational flow:

```text
claims -> resolver -> candidates -> policy -> accepted SSOT
```

## System laws

1. Store once
2. Derive many
3. Project late
4. Cache only when hot
5. Graph can disagree
6. SSOT cannot disagree with itself
7. Every fact traces to raw
8. All axes stay orthogonal
9. Append-only by default
10. No silent mutation

## Proof and trust contract

- all events signed with `ed25519`
- payloads are CID-addressed with `cSHAKE256`
- audit log is append-only
- every action must be verifiable via `/verify`
- if signing or audit fails: enter SAFE mode and recover

## Runtime rules

Modes:

- NORMAL
- GUARDED
- SAFE

Every toggle must expose:

```text
name + current + next + reason
```

No hidden state.

Recovery contract:

```text
recover()
-> restore last-known-good
-> enable SAFE mode
-> restart services
-> verify health
```

No failure should require manual debugging to recover.

## Governance

Load and follow:

- [`TODO_TIERS.md`](TODO_TIERS.md)
- [`REDTEAM.md`](REDTEAM.md)

Rules:

- batch by todo tier
- reject mixed-tier escalation
- `P4` and `P5` require manual approval
- `P5` cannot auto-promote
- Red Team failure blocks promotion

## AI coding loop

```text
generate -> classify -> batch -> test -> redteam -> promote
```

Operational defaults:

- operate locally first
- prove, not claim
- fail safely
- recover deterministically
- keep the system minimal, orthogonal, and non-redundant
- centrally reference operating rules and invariants instead of restating them
