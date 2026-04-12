# ARK SSOT MVP

This repo is the standalone Phase 0 single-source-of-truth MVP. It keeps the runtime path intentionally small:

- source-specific hooks: `/webhook/ark/homeassistant`, `/webhook/ark/jellyfin`, `/webhook/ark/unifi`
- generic hook: `/webhook/ark/event`
- bounded inference: only unknown or incomplete payloads go to Ollama
- idempotent persistence: Postgres owns dedupe, RLE merge, and snapshots
- immediate visibility: fallback events are logged to `ark_ingest_anomaly` and highlighted in Grafana

## What is here

- `ingest/connectors/` documents the source-side hook and mapping rules.
- `ingest/n8n/ark-mvp-ingest.json` is the importable ingest workflow.
- `storage/postgres/schema.sql` bootstraps the database and SQL functions.
- `compute/duckdb/ark_current.sql` exposes a read-only current-state view contract.
- `insight/grafana/autonomy-dashboard.json` is the Grafana v11 dashboard.
- `infra/` contains the compose stack and environment template.
- `apps/docker-compose.yml` is an optional stack for Home Assistant, Jellyfin, and UniFi Network Application (with MongoDB); config and runtime data live under `apps/`.
- `vendor/ultimate-jellyfin-stack/` holds a reference Jellyfin compose layout.

## Quick start

1. Open a shell in `ark-ssot-mvp/infra` and copy the env file.

```powershell
Copy-Item .env.example .env
```

2. Create the runtime directories expected by Compose.

```powershell
New-Item -ItemType Directory -Force -Path `
  .\runtime\postgres, `
  .\runtime\n8n, `
  .\runtime\grafana, `
  .\runtime\ollama, `
  .\runtime\mqtt\config, `
  .\runtime\mqtt\data, `
  .\runtime\mqtt\log, `
  .\runtime\mqtt\certs | Out-Null
```

3. Create `.\runtime\mqtt\config\mosquitto.conf`, `.\runtime\mqtt\config\aclfile`, and `.\runtime\mqtt\config\passwd` using the examples in `ingest/connectors/mqtt-security.md`. Drop your TLS files into `.\runtime\mqtt\certs`.

4. Start the stack from `infra/docker-compose.yml`.

```powershell
docker compose up -d
```

5. Pull the Ollama model once the container is running.

```powershell
docker compose exec ollama ollama pull $env:ARK_OLLAMA_MODEL
```

6. Open the services:

- n8n: `http://localhost:5678`
- Grafana: `http://localhost:3300`
- Postgres: `localhost:55432`
- Ollama: `http://localhost:11434`
- MQTT TLS listener: `localhost:8883`

7. In n8n:

- create a Postgres credential that points to `postgres:5432` inside the Compose network
- import `ingest/n8n/ark-mvp-ingest.json`
- assign the credential to the `Persist Signal` node
- activate the workflow

8. In Grafana:

- create a PostgreSQL datasource that points to `postgres:5432`, database `ark_ssot`, user `ark`
- import `insight/grafana/autonomy-dashboard.json`

## Operational notes

- `schema.sql` is mounted into Postgres init and runs automatically on the first empty database volume.
- Replaying the same event is safe. Exact duplicates are absorbed by `ark_event_receipt`; adjacent identical spans are merged by `upsert_delta()`.
- If Ollama is unavailable or classification is uncertain, the workflow stores the event as `unknown.raw` and writes an anomaly row instead of dropping the payload.

## Test commands

Known Home Assistant event:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:5678/webhook/ark/homeassistant -ContentType 'application/json' -Body '{"entity_id":"sensor.living_room_temperature","state":"72.4","attributes":{"device_class":"temperature","unit_of_measurement":"F","friendly_name":"Living Room Temperature"},"last_changed":"2026-04-10T20:10:30Z"}'
```

Known Jellyfin event:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:5678/webhook/ark/jellyfin -ContentType 'application/json' -Body '{"NotificationType":"PlaybackStart","Timestamp":"2026-04-10T20:15:00Z","ItemId":"episode-001","ItemType":"Episode","Name":"Pilot","SeriesName":"Example Show","UserName":"trevl","DeviceName":"Living Room TV"}'
```

Unknown generic event:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:5678/webhook/ark/event -ContentType 'application/json' -Body '{"source":"lab","payload_kind":"mystery","observed_at":"2026-04-10T20:20:00Z","raw":{"beam":17,"flux":"high","state":"???","nested":{"alpha":1,"beta":true}}}'
```
