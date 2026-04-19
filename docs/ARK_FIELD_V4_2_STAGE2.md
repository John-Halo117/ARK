# ARK-Field v4.2 — Stage 2

## Orthogonal, SOLID, DRY, Idempotent Architecture

- `internal/ingestion/service.go` is now orchestration-only with dependency inversion through interfaces:
  - `CommitSource`
  - `DedupeSequencer`
  - `Publisher`
  - `StabilityEvaluator`
- Adapter implementations are isolated by boundary:
  - `internal/adapters/gitcommit/source.go`
  - `internal/adapters/redisstate/store.go`
  - `internal/adapters/natspub/publisher.go`
  - `internal/adapters/stabilitywrap/evaluator.go`
- Shared env parsing is DRY in `internal/config/env.go`.
- Idempotency is enforced with Redis reservation + pending marker + final commit record.
- Ingestion Leader explicitly blocks duplicate-in-flight state hashes.

## Ingestion Leader calling Stability Kernel

`internal/ingestion/service.go` invokes kernel evaluation before publish:

```go
decision := s.Stability.Evaluate(obsBuilder(req, commit))
if decision.Freeze {
    _ = s.Store.Release(stateHash)
    return nil, false, fmt.Errorf("stability rejected event: %s", decision.Reason)
}
```
