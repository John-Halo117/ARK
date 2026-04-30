# Placement Rules

All code MUST live in either `internal/` or `external/`.

## Decision Rule

Ask:

> Does ARK still fully function offline without this?

- YES → internal/
- NO → external/

## Hard Constraints

- internal/ MUST NOT import or depend on external/
- external/ MAY depend on internal/
- shared interfaces must live in internal/

## Anti-Drift Rules

Reject code that:
- mixes internal logic with external calls
- hides network calls inside internal/
- bypasses connectivity mode checks

## CI Enforcement (future)

- fail if internal/ contains external URLs
- fail if external/ is required by core services
- fail if placement rule is violated

## Outcome

Clean separation:

internal = deterministic core
external = optional capability

No ambiguity.
