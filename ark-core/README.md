# ARK core (merged)

This folder is the **single workspace** for:

1. **Platform stack** (repo root) - NATS + DuckDB worker + mesh + autoscaler + AAR + Composio bridge + Grafana + Meilisearch. See `compose.yaml`, `duckdb/`, `mesh/`, `runtime/`, `agents/`, tests, and `requirements-dev.txt`.
2. **SSOT MVP** (`ark-ssot-mvp/`) - Phase 0 ingestion: Postgres, n8n, Grafana, Ollama, MQTT, webhooks, SQL schema, n8n workflow export, optional Home Assistant / Jellyfin / UniFi apps. Start at `ark-ssot-mvp/README.md`.
3. **ARK-Field v4.2 foundation** - Git-first event ingestion with the new `docker-compose.yml`, Go service scaffolding in `cmd/`, shared models in `internal/models/`, and Git hook hand-off in `.githooks/`.

## Layout

| Area | Role |
| --- | --- |
| `compose.yaml` | Legacy merged platform/event backbone Compose |
| `docker-compose.yml` | ARK-Field v4.2 foundation stack |
| `cmd/` | Go service entrypoints for Ingestion Leader, Stability Kernel, and NetWatch |
| `internal/models/` | Shared ARK-Field data models |
| `.githooks/post-commit` | Git commit hand-off stub into the Ingestion Leader |
| `docs/ark-field-v4.2-foundation.md` | Updated directory tree for Stage 1 |
| `ark-ssot-mvp/infra/docker-compose.yml` | SSOT core stack (Postgres, n8n, Grafana, Ollama, MQTT) |
| `ark-ssot-mvp/apps/docker-compose.yml` | Optional media / Home Assistant / UniFi apps |
| `ark-ssot-mvp/storage/postgres/schema.sql` | Postgres bootstrap |
| `ark-ssot-mvp/ingest/n8n/ark-mvp-ingest.json` | n8n workflow import |

## Verify / CI

From this directory:

```powershell
.\scripts\verify.ps1
go test ./...
docker compose -f docker-compose.yml config
```

## Note on duplicates

If you still have an older `ark-ssot-mvp` folder next to `ark-core` under `ark/`, compare and remove the duplicate after confirming this tree. Optional docs such as `apps/BEFORE_vs_AFTER.md` were not copied if you only use this merge; copy them manually if needed.
