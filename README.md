# ARK workspace

This folder holds **one project**: [`ark-ssot-mvp`](ark-ssot-mvp/README.md) (ARK SSOT MVP). Start there for Phase 0 single-source-of-truth ingestion (webhooks via n8n, Postgres, optional Ollama, Grafana).

## Layout

| Piece | Role |
| --- | --- |
| [`ark-ssot-mvp/ingest/connectors/`](ark-ssot-mvp/ingest/connectors/) | Connector notes (Home Assistant, Jellyfin, UniFi, MQTT) |
| [`ark-ssot-mvp/ingest/n8n/ark-mvp-ingest.json`](ark-ssot-mvp/ingest/n8n/ark-mvp-ingest.json) | Importable n8n workflow |
| [`ark-ssot-mvp/storage/postgres/schema.sql`](ark-ssot-mvp/storage/postgres/schema.sql) | Postgres bootstrap |
| [`ark-ssot-mvp/compute/duckdb/ark_current.sql`](ark-ssot-mvp/compute/duckdb/ark_current.sql) | DuckDB current-state contract |
| [`ark-ssot-mvp/insight/grafana/autonomy-dashboard.json`](ark-ssot-mvp/insight/grafana/autonomy-dashboard.json) | Grafana dashboard |
| [`ark-ssot-mvp/infra/docker-compose.yml`](ark-ssot-mvp/infra/docker-compose.yml) | Core stack: Postgres, n8n, Grafana, Ollama, MQTT |
| [`ark-ssot-mvp/apps/docker-compose.yml`](ark-ssot-mvp/apps/docker-compose.yml) | Optional apps: Home Assistant, Jellyfin, UniFi |
| [`ark-ssot-mvp/vendor/ultimate-jellyfin-stack/`](ark-ssot-mvp/vendor/ultimate-jellyfin-stack/) | Vendored Jellyfin reference |

There is no separate application service in this workspace beyond Compose, SQL, n8n JSON, and docs; see [`ark-ssot-mvp/README.md`](ark-ssot-mvp/README.md) for quick start and test webhooks.
