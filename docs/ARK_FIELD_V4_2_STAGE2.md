# ARK-Field v4.2 — Stage 2

## Added
- `internal/stability/kernel.go`: Stability Kernel v4.2 equations, guards, and recovery rule in one module.
- `internal/ingestion/service.go`: Ingestion Leader flow (normalize diff, state hash, Redis dedupe, sequence, CID wrap, stability gate, NATS publish).
- `internal/transport/redis.go`: minimal RESP Redis client (`PING`, `GET`, `SET`, `INCR`).
- `internal/transport/nats.go`: minimal NATS client (`CONNECT`, `PING`, `PUB`).

## Ingestion Leader calling Stability Kernel
`internal/ingestion/service.go` invokes kernel evaluation before publish:

```go
decision := s.Kernel.Evaluate(defaultObservation())
if decision.Freeze {
    return nil, false, fmt.Errorf("stability freeze: %s", decision.Reason)
}
```
