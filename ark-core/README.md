# ARK core (merged)

This folder is the **single workspace** for:

1. **Platform stack** (repo root) — NATS + DuckDB worker + mesh + autoscaler + AAR + Composio bridge + Grafana + Meilisearch. See `compose.yaml`, `duckdb/`, `mesh/`, `runtime/`, `agents/`, tests, and `requirements-dev.txt`.

2. **SSOT MVP** (`ark-ssot-mvp/`) — Phase 0 ingestion: Postgres, n8n, Grafana, Ollama, MQTT, webhooks, SQL schema, n8n workflow export, optional Home Assistant / Jellyfin / UniFi apps. Start at `ark-ssot-mvp/README.md`.

## Layout

| Area | Role |
| --- | --- |
| `compose.yaml` | Platform / event backbone Compose |
| `ark-ssot-mvp/infra/docker-compose.yml` | SSOT core stack (Postgres, n8n, Grafana, …) |
| `ark-ssot-mvp/apps/docker-compose.yml` | Optional media / HA / UniFi apps |
| `ark-ssot-mvp/storage/postgres/schema.sql` | Postgres bootstrap |
| `ark-ssot-mvp/ingest/n8n/ark-mvp-ingest.json` | n8n workflow import |

## Verify / CI

From this directory:

```powershell
.\scripts\verify.ps1
```

## Note on duplicates

If you still have an older `ark-ssot-mvp` folder next to `ark-core` under `ark/`, compare and remove the duplicate after confirming this tree. Optional docs such as `apps/BEFORE_vs_AFTER.md` were not copied if you only use this merge; copy them manually if needed.
