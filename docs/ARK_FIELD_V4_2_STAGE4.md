# ARK-Field v4.2 — Stage 4

## Added
- `cmd/mqtt-bridge/main.go`
  - `POST /v1/mqtt/forward` to transform MQTT payloads into CID events and publish to NATS.
  - Stability-kernel gate on every bridge forward path.
- `internal/wiring/mqttbridge.go`
  - MQTT→CID event bridge module with stability gate.
- `internal/projections/projector.go`
  - Redis projection writer (`ark:projection:<seq>` keys).
  - DuckDB projection sink as append-only NDJSON.
  - Replay stub support (`Replay` + query parser helper).
- `Dockerfile.mqtt-bridge`
- `.cursorrules` operation guidelines.

## Updated
- `cmd/ingestion-leader/main.go`
  - projection write after accepted ingest publish.
  - replay stub endpoint: `GET /v1/replay?from=<n>&to=<n>`.
- `docker-compose.yml`
  - removed old `opencode`/`openwolf` agents.
  - added `mqtt-bridge` service.
