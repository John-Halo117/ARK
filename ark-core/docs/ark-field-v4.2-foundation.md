# ARK-Field v4.2 Stage 1 Foundation

This scaffold introduces the minimum repo shape needed for the ARK-Field v4.2
pipeline while preserving the legacy `compose.yaml` stack.

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
|-- docs/
|   `-- ark-field-v4.2-foundation.md
|-- internal/
|   `-- models/
|       |-- cid_object.go
|       |-- event.go
|       `-- stability_metrics.go
|-- docker-compose.yml
|-- go.mod
`-- compose.yaml
```

## Stage 1 Notes

- `docker-compose.yml` is the new ARK-Field v4.2 stack for the Git-first event
  backbone: NATS JetStream, Redis, Ingestion Leader, Stability Kernel,
  WireGuard, and NetWatch.
- `compose.yaml` is left untouched as the legacy merged platform stack.
- All new services mount the NAS at `/mnt/nas`, with the CAS root reserved at
  `/mnt/nas/cas`.
- `.githooks/post-commit` is a stub hand-off from Git commits into the
  Ingestion Leader pipeline.
- `internal/models` contains the canonical Stage 1 Go models that Stage 2 will
  use for event normalization and stability evaluation.
