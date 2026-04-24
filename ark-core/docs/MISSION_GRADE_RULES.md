# ARK Mission-Grade Rules

`MISSION_GRADE_RULES.md` is the canonical operating doctrine for turning ARK's
architecture language into enforceable engineering posture. Other docs should
reference this file instead of restating these rules in parallel.

The machine-readable sources live in:

- `config/operating_rules.json`
- `config/system_invariants.json`

## Mission posture

ARK must behave like a governed mission system:

- deterministic where action becomes irreversible
- adversarial by default on all external boundaries
- append-only for evidence and accepted state transitions
- explicit about confidence, uncertainty, and provenance
- recoverable without heroic operator debugging
- observable enough to explain what changed and why

## Central rules

### 1. Sovereign kernel rule

Only the bounded control plane may:

- accept operational truth
- promote state
- authorize external action
- append authoritative audit evidence
- switch between NORMAL, GUARDED, and SAFE

### 2. Truth boundary rule

- observations may disagree
- claims may conflict
- projections may be stale
- only SSOT is actionable truth
- every accepted value must trace to raw evidence

### 3. Deterministic decision rule

The following paths must be replayable from the same inputs:

- classify
- resolve
- promote
- recover
- verify

### 4. Explicit state transition rule

Every governed transition must record:

- previous state
- next state
- reason
- actor or subsystem
- policy version
- evidence or source references
- timestamp

### 5. No silent mutation rule

The system must never:

- overwrite accepted truth without lineage
- mutate policy-relevant state without an event
- hide degraded operation behind success language

### 6. Bounded execution rule

Every action-capable subsystem must define:

- timeout
- retry policy
- budget
- failure mode
- verify step

### 7. Graceful degradation rule

If a dependency is missing or untrusted, ARK must narrow behavior rather than
pretend success. SAFE mode is preferred over ambiguous automation.

## Engineering implications

These rules imply:

1. contracts must be versioned and validated
2. audit trails must be append-only and queryable
3. accepted truth must be separated from claims
4. red-team scenarios must block promotion when they fail
5. every automation path must define recovery

## Maturity test

A subsystem is not mission-grade unless an operator can answer:

1. what does it believe
2. why does it believe that
3. what evidence supports it
4. what policy permitted the action
5. how it recovers when a dependency fails
