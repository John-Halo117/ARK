# ARK-Field v4.2 — Stage 1 Foundation

## Updated repository tree (Stage 1)

```text
.
├── .githooks/
│   └── post-commit
├── cmd/
│   ├── ingestion-leader/
│   │   └── main.go
│   ├── netwatch/
│   │   └── main.go
│   └── stability-kernel/
│       └── main.go
├── docs/
│   └── ARK_FIELD_V4_2_STAGE1.md
├── internal/
│   └── models/
│       └── event.go
├── Dockerfile.ingestion-leader
├── Dockerfile.netwatch
├── Dockerfile.stability-kernel
├── docker-compose.yml
└── go.mod
```

## Notes

- `docker-compose.yml` now defines the Stage-1 core services: Ingestion Leader, Stability Kernel, WireGuard sidecar, NetWatch, plus Redis and NATS for pipeline dependencies.
- CAS storage is mounted from host NAS path `/mnt/nas` into `/cas` for Ingestion Leader.
- Post-commit hook stub is provided at `.githooks/post-commit`; set with:

```bash
git config core.hooksPath .githooks
```
