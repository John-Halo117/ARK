# ARK Constitution v1
**Bounded · Verifiable · Contained Systems**

## Core Law

Bound everything.
Observe everything.
Trust nothing unverified.
Keep failure local.
Promote only what proves itself.

---

## Core Loop Law (Non-Negotiable)

Sense → Compress → Judge → Act → Verify → Remember

Every subsystem MUST implement this loop.

Missing any stage = invalid system.

---

## Enforcement Rules

1. No action without Judge
2. No action without Verify
3. No event without Compress
4. No state change without Remember
5. No unbounded execution
6. No silent failure

---

## ARK 10 Rules

1. No unbounded feedback loops
2. All processes are time and resource capped
3. All resources are pre-budgeted
4. Systems are modular and small
5. Every subsystem asserts health continuously
6. State is local, not global
7. Every action returns a verifiable result
8. Flows are linear, observable, debuggable
9. Interfaces are strict and minimal
10. Any anomaly triggers immediate visibility or fail-safe

---

## Master Invariants

### Boundedness
Nothing runs or grows without limits.

### Verifiability
Nothing is trusted without proof.

### Containment
Failures do not propagate by default.

---

## Enforcement

These rules must exist in code, CI, runtime, and policy.
If a rule is not enforced, it does not exist.

---

## Promotion Rule

Only changes that pass tests, satisfy reliability thresholds, and comply with all invariants may be promoted.

---

## Failure Rule

On any anomaly, prefer safe halt over uncertain continuation.
