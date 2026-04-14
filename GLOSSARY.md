# ARK Glossary of Standards, Terms & Naming Conventions

> Canonical reference for every naming convention, delimiter rule, and domain
> term used across the ARK codebase. All new code **must** follow these rules.
> Constants live in [`ark/subjects.py`](ark/subjects.py) — import from there,
> never hard-code subject strings.

---

## 1. NATS Subject Naming

### 1.1 Format

```
ark.<domain>.<action>[.<qualifier>…]
```

| Rule | Detail |
|------|--------|
| **Prefix** | Every subject starts with `ark.` |
| **Case** | All lowercase — no camelCase, no UPPER |
| **Delimiter** | Dots (`.`) only — no slashes, dashes, or underscores between tokens |
| **Token charset** | `[a-z0-9_]` within a single token; underscores allowed inside tokens (e.g. `queue_depth`) |
| **Max length** | 256 characters |

### 1.2 Domains

| Domain | Purpose | Examples |
|--------|---------|----------|
| `mesh` | Service registration & discovery | `ark.mesh.register`, `ark.mesh.heartbeat`, `ark.mesh.registered` |
| `call` | Capability invocation (request) | `ark.call.<service>.<capability>` |
| `reply` | Capability response | `ark.reply.<request_id>` |
| `event` | Domain events from emitters | `ark.event.climate.temperature`, `ark.event.media.playback` |
| `metrics` | Telemetry / time-series | `ark.metrics.temperature`, `ark.metrics.network` |
| `anomaly` | Anomaly detection signals | `ark.anomaly.detected` |
| `system` | Autoscaler demand/health signals | `ark.system.queue_depth.<service>`, `ark.system.ashi` |
| `spawn` | Scaling lifecycle | `ark.spawn.confirmed` |

### 1.3 Wildcards

| Token | Meaning | Use when |
|-------|---------|----------|
| `*` | Matches **exactly one** dot-delimited token | Last token varies but depth is fixed (e.g. `ark.system.queue_depth.*`) |
| `>` | Matches **one or more** trailing tokens | Capability names contain dots (e.g. `ark.call.opencode.>` matches `ark.call.opencode.code.analyze`) |

**Critical rule**: Agents and emitters subscribe with `>` for capability calls
because capabilities are multi-token (`code.analyze`, `external.email`).

### 1.4 Subject Constant Module

All subject strings are defined in **`ark/subjects.py`**. Source code must
import constants and helpers from there:

```python
from ark.subjects import (
    MESH_REGISTER,                     # "ark.mesh.register"
    call_subject,                       # call_subject("opencode", "code.analyze")
    call_subscribe_subject,             # "ark.call.opencode.>"
    reply_subject,                      # "ark.reply.req-123"
    parse_capability_from_subject,      # "ark.call.opencode.code.analyze" → "code.analyze"
)
```

**Never** use f-strings like `f"ark.call.{service}.{cap}"` — use `call_subject(service, cap)`.

---

## 2. Service Names

| Rule | Detail |
|------|--------|
| **Regex** | `^[a-z][a-z0-9_-]{0,63}$` (see `ark/security.py:SERVICE_NAME_RE`) |
| **Case** | Lowercase only |
| **Charset** | Letters, digits, hyphens, underscores |
| **Max length** | 64 characters |
| **No dots** | Dots are NATS token separators — never in service names |

### Registered Service Names

| Name | Module | Role |
|------|--------|------|
| `opencode` | `agents/opencode/agent.py` | Reasoning, code intelligence |
| `openwolf` | `agents/openwolf/agent.py` | Anomaly detection, ASHI health |
| `composio` | `agents/composio/agent.py` | External API bridge (email, GitHub, Slack…) |
| `homeassistant` | `emitters/homeassistant_emitter.py` | IoT state change emitter |
| `jellyfin` | `emitters/jellyfin_emitter.py` | Media playback emitter |
| `unifi` | `emitters/unifi_emitter.py` | Network device emitter |

---

## 3. Capability Names

| Rule | Detail |
|------|--------|
| **Regex** | `^[a-z][a-z0-9_.]{0,127}$` (see `ark/security.py:CAPABILITY_RE`) |
| **Case** | Lowercase only |
| **Structure** | `<domain>.<action>` — always at least two tokens |
| **Delimiter** | Dots — these become additional NATS subject tokens |
| **Max length** | 128 characters |

### Registered Capabilities

| Capability | Service | Description |
|------------|---------|-------------|
| `code.analyze` | opencode | Static analysis |
| `code.transform` | opencode | Refactor / migrate / optimize |
| `code.generate` | opencode | Code generation from spec |
| `reasoning.plan` | opencode | Execution planning |
| `reasoning.decompose` | opencode | Problem decomposition |
| `anomaly.detect` | openwolf | Anomaly detection |
| `system.health` | openwolf | System health computation |
| `metrics.ingest` | openwolf | Metric ingestion |
| `ashi.compute` | openwolf | ASHI health index |
| `external.email` | composio | Email via Composio |
| `external.github` | composio | GitHub actions |
| `external.slack` | composio | Slack messaging |
| `external.notion` | composio | Notion operations |
| `external.calendar` | composio | Calendar operations |
| `external.crm` | composio | CRM operations |
| `event.home_assistant` | homeassistant | HA event retrieval |
| `state.device_update` | homeassistant | Device state mutation |
| `climate.temperature` | homeassistant | Temperature reading |
| `light.toggle` | homeassistant | Light on/off |
| `sensor.reading` | homeassistant | Sensor value |
| `media.playback` | jellyfin | Playback status |
| `media.library` | jellyfin | Library info |
| `media.search` | jellyfin | Media search |
| `playback.status` | jellyfin | Active session status |
| `library.items` | jellyfin | Library item listing |
| `network.devices` | unifi | Device inventory |
| `network.events` | unifi | Network event log |
| `network.stats` | unifi | Network statistics |
| `device.status` | unifi | Single device status |
| `wireless.clients` | unifi | Wireless client list |
| `network.health` | unifi | Network health score |

---

## 4. Instance IDs

| Rule | Detail |
|------|--------|
| **Regex** | `^[a-zA-Z0-9_-]{1,64}$` (see `ark/security.py:INSTANCE_ID_RE`) |
| **Generated by** | `str(uuid.uuid4())[:12]` or `INSTANCE_ID` env var |
| **Max length** | 64 characters |

---

## 5. Entity IDs

Used by Home Assistant emitter for device/sensor references.

| Rule | Detail |
|------|--------|
| **Regex** | `^[a-zA-Z0-9._-]{1,256}$` (see `ark/security.py:ENTITY_ID_RE`) |
| **Examples** | `climate.living_room`, `sensor.humidity`, `light.kitchen` |

---

## 6. Event Schema

Defined in `ark/event_schema.py`.

### EventSource (enum)

| Value | Constant |
|-------|----------|
| `emitter.homeassistant` | `EventSource.EMITTER_HA` |
| `emitter.jellyfin` | `EventSource.EMITTER_JELLYFIN` |
| `emitter.unifi` | `EventSource.EMITTER_UNIFI` |
| `agent.opencode` | `EventSource.AGENT_OPENCODE` |
| `agent.openwolf` | `EventSource.AGENT_OPENWOLF` |
| `agent.composio` | `EventSource.AGENT_COMPOSIO` |
| `ark.core` | `EventSource.ARK_CORE` |
| `system` | `EventSource.SYSTEM` |

> **Note**: `EventSource` values use dots but are **not** NATS subjects — they
> are stored in DuckDB's `events.source` column.

### EventType (enum)

`metric` · `state` · `anomaly` · `decision` · `error` · `status`

### LKS Phases

`stable` · `drift` · `unstable` · `critical`

### Payload Limits

| Constraint | Value |
|------------|-------|
| Max payload size | 1 MiB (1,048,576 bytes) |
| Max event ID length | 128 characters |
| Max tags per event | 64 |
| Max tag key length | 128 characters |
| Max tag value length | 512 characters |

---

## 7. Security Validation Regexes

All defined in `ark/security.py`:

| Name | Pattern | Used for |
|------|---------|----------|
| `SERVICE_NAME_RE` | `^[a-z][a-z0-9_-]{0,63}$` | Service names |
| `INSTANCE_ID_RE` | `^[a-zA-Z0-9_-]{1,64}$` | Instance IDs |
| `CAPABILITY_RE` | `^[a-z][a-z0-9_.]{0,127}$` | Capability names |
| `ENTITY_ID_RE` | `^[a-zA-Z0-9._-]{1,256}$` | HA entity IDs |
| `NATS_SUBJECT_RE` | `^[a-zA-Z0-9._*>-]+$` | NATS subjects |
| `_SAFE_CMD_RE` | `^[a-zA-Z0-9_.=/:@-]+$` | Docker CLI arguments |

---

## 8. ASHI (ARK System Health Index)

Computed by OpenWolf agent.

```
ASHI = 100 − (anomaly_count × 15)

Level mapping:
  90+   → optimal
  70–89 → good
  50–69 → fair
  <50   → critical
```

Autoscaler triggers recovery spawns when ASHI < 60.

---

## 9. Autoscaler Thresholds

| Service | Queue threshold | Latency threshold (ms) | Min instances | Max instances |
|---------|----------------|----------------------|---------------|---------------|
| opencode | 10 | 1000 | 1 | 5 |
| openwolf | 20 | 500 | 1 | 3 |
| composio | 50 | 2000 | 1 | 10 |

---

## 10. Docker Container Naming

Format: `ark-<service>-<instance_id>`

Example: `ark-opencode-a1b2c3d4e5f6`

Security flags applied by `build_safe_docker_cmd()`:
- `--read-only`
- `--cap-drop ALL`
- `--security-opt no-new-privileges:true`
- `--pids-limit 256`
- `--network ark-net`

---

## 11. HTTP API Paths

| Service | Port | Endpoints |
|---------|------|-----------|
| Gateway | 8080 | `GET /api/mesh`, `GET /api/service/{name}`, `GET /api/route/{capability}`, `POST /api/call/{capability}`, `GET /api/events`, `GET /api/metrics/{source}`, `GET /api/status`, `GET /api/health` |
| Mesh Registry | 7000 | `GET /api/mesh`, `GET /api/service/{service}`, `GET /api/route/{capability}`, `GET /api/health` |
| Autoscaler | 7001 | `GET /api/instances/{service}`, `POST /api/spawn`, `GET /api/health` |

---

## 12. Rate Limiting Defaults

| Limiter | Rate (req/s) | Burst | Scope |
|---------|-------------|-------|-------|
| `api_rate_limiter` | 20 | 100 | Per-IP on all HTTP endpoints |
| `registration_rate_limiter` | 5 | 20 | Per-service on mesh registration |

---

## 13. Middleware Stack Order

Applied outermost → innermost on every HTTP request:

1. `request_id_middleware` — assigns `X-Request-ID`
2. `error_shield_middleware` — catches unhandled exceptions, returns generic 500
3. `secure_headers_middleware` — `X-Content-Type-Options`, `X-Frame-Options`, HSTS, etc.
4. `rate_limit_middleware` — per-IP token-bucket rate limiting
5. `auth_middleware` — bearer token validation (passthrough when `ARK_API_TOKENS` unset)

---

## 14. File Layout

```
ark/
  subjects.py        ← NATS subject constants (single source of truth)
  security.py        ← validation, sanitization, auth, middleware, Docker hardening
  maintenance.py     ← resilient NATS, shutdown coordinator, health checks, periodic tasks
  event_schema.py    ← ArkEvent, LKS, EventSource, EventType
  duck_client.py     ← DuckDB read/write interface
  api_gateway.py     ← HTTP gateway (port 8080)
  mesh_registry.py   ← service discovery (port 7000)
  autoscaler.py      ← demand-based scaling (port 7001)

agents/
  opencode/agent.py  ← code intelligence agent
  openwolf/agent.py  ← anomaly detection / ASHI agent
  composio/agent.py  ← external API bridge agent
  rube/agent.py      ← graph reasoning agent (sync, no NATS)

emitters/
  homeassistant_emitter.py  ← IoT state change emitter
  jellyfin_emitter.py       ← media playback emitter
  unifi_emitter.py          ← network device emitter

tests/
  ark/               ← core module tests
  agents/            ← agent tests
  emitters/          ← emitter tests
```
