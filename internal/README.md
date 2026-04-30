# internal/

Sovereign ARK core.

Everything required for ARK to function offline by default belongs here.

## Put code here if it is:
- required for core operation
- local-first
- deterministic
- policy-enforced
- part of the control plane, execution plane, storage plane, or observability plane

## Examples
- kernels
- ingestion
- models
- transport
- local CI/CD
- local AI loops
- local storage and truth systems

## Rule
If ARK cannot boot, run, test, repair, and converge without it, it belongs in `internal/`.
