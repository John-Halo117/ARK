# ARK UNIFIED SPEC - GORDON-READY DEPLOYMENT

> A self-scaling, event-driven operating system where services are grown (not deployed) in response to event pressure, with capability-based routing and NATS-first architecture.

---

## Architecture Overview

```
Inputs (IoT / APIs / users)
        ↓
MQTT (reflex layer)
        ↓
NATS JetStream (event backbone, primary)
        ↓
Mesh Registry (service discovery via capabilities)
        ↓
Agents (OpenCode, OpenWolf, Composio)
        ↓
Execution (n8n, Home Assistant, MCP)
        ↓
DuckDB (SSOT truth layer)
        ↓
Observability (Grafana, Meilisearch)
        ↓
Autoscaler (feedback → spawn new services)
```

---

## System Layers

### 1. Event Backbone (NATS JetStream)
- **Primary transport**: All system communication flows through NATS
- **No direct service-to-service TCP calls**: Everything is event-driven
- **Topics**:
  - `ark.mesh.register` - Service registration
  - `ark.mesh.heartbeat` - Health signals
  - `ark.call.<service>.<capability>` - Capability invocation
  - `ark.reply.<request_id>` - Responses
  - `ark.metrics.*` - System metrics
  - `ark.anomaly.detected` - Anomalies
  - `ark.system.queue_depth.*` - Demand signals
  - `ark.system.latency.*` - Latency signals
  - `ark.spawn.request` - Scale-up requests
  - `ark.spawn.confirmed` - Scale-up confirmations

### 2. Service Mesh Registry
- **Discovery via capabilities**, not IP addresses
- **Registration event**:
  ```json
  {
    "service": "opencode",
    "instance_id": "uuid",
    "capabilities": ["code.analyze", "code.generate"],
    "load": 0.3,
    "ttl": 10
  }
  ```
- **Routing**: Registry maintains capability → instance mapping
- **Load balancing**: Routes to least-loaded instance

### 3. Intelligence Layer
#### OpenCode
- **Capabilities**: `code.analyze`, `code.transform`, `code.generate`, `reasoning.plan`, `reasoning.decompose`
- **Role**: Reasoning, planning, code intelligence

#### OpenWolf
- **Capabilities**: `anomaly.detect`, `system.health`, `metrics.ingest`, `ashi.compute`
- **Role**: System health monitoring, anomaly detection, ASHI computation

#### Composio Bridge
- **Capabilities**: `external.email`, `external.github`, `external.slack`, `external.notion`, `external.calendar`, `external.crm`
- **Role**: External world execution via Composio APIs

### 4. Execution Layer
- **n8n**: Workflow orchestration
- **Home Assistant**: IoT execution
- **MCP**: Model Context Protocol for tool access

### 5. Truth Layer (DuckDB)
- **Single Source of Truth**
- **Tables**:
  - `events` - All system events
  - `state` - Service state projections
  - `metrics` - Time-series metrics

### 6. Autoscaler
- **Monitors**: Queue depth, latency, ASHI degradation
- **Spawns**: New service instances via Docker when demand exceeds threshold
- **Terminates**: Idle instances after cooldown
- **Registers**: New instances automatically into mesh

---

## Service Registration & Discovery

### Agent Registration Flow

```python
# Agent startup
event = {
    "service": "opencode",
    "instance_id": "abc123",
    "capabilities": ["code.analyze"],
    "ttl": 10  # Heartbeat expiry
}
await nc.publish("ark.mesh.register", json.dumps(event))
```

### Capability Routing

```python
# Route a capability request
# Subject: ark.call.opencode.code.analyze
# Registry maps capability → service → instance (least-loaded)
```

### Heartbeat Loop

```python
# Every 5 seconds
await nc.publish("ark.mesh.heartbeat", {
    "service": "opencode",
    "instance_id": "abc123",
    "load": 0.3,
    "healthy": True
})
```

---

## Autoscaling Mechanism

### Demand Signals

Services emit queue depth and latency:

```python
await js.publish("ark.system.queue_depth.opencode", {
    "depth": 25,
    "timestamp": "2024-01-15T10:30:00Z"
})
```

### Scaling Decision

```python
if queue_depth > threshold and instance_count < max_instances:
    spawn_instance(service)
```

### Scale-Down Decision

```python
if idle_time > cooldown and queue_depth == 0:
    terminate_instance(service)
```

---

## Event Flow Example: Code Generation Request

1. **User/API triggers**: `POST /api/generate` with code spec
2. **n8n receives**: Creates workflow event
3. **Event published**: `ark.call.opencode.code.generate`
4. **Mesh routes**: Registry finds least-loaded OpenCode instance
5. **Agent processes**: `code.generate()` capability handler
6. **Agent replies**: Publishes to `ark.reply.<request_id>`
7. **n8n receives**: Result available
8. **DuckDB records**: Event + result logged
9. **Metrics emitted**: Processing time, success/failure
10. **Autoscaler monitors**: If latency spikes, spawns new OpenCode instance

---

## Agent Contract

All agents must:

1. **Connect to NATS**
2. **Register capabilities on startup**
3. **Subscribe to `ark.call.<service>.<capability>` topics**
4. **Heartbeat every 5 seconds**
5. **Reply to requests via `ark.reply.<request_id>`**
6. **Handle graceful shutdown**

---

## Mesh Registry API

### Check Mesh Status
```bash
curl http://localhost:7000/api/mesh
```

Response:
```json
{
  "services": 3,
  "instances": 5,
  "capabilities": 15,
  "service_details": {
    "opencode": {
      "instance_count": 2,
      "total_load": 0.6,
      "healthy_count": 2
    }
  }
}
```

### Route a Capability
```bash
curl http://localhost:7000/api/route/code.analyze
```

Response:
```json
{
  "capability": "code.analyze",
  "service": "opencode",
  "instance_id": "abc123"
}
```

### Get Service Info
```bash
curl http://localhost:7000/api/service/opencode
```

---

## Autoscaler API

### Get Service Instances
```bash
curl http://localhost:7001/api/instances/opencode
```

### Spawn Instance
```bash
curl -X POST http://localhost:7001/api/spawn \
  -H "Content-Type: application/json" \
  -d '{"service": "opencode"}'
```

---

## Quick Start

### 1. Build all images
```bash
docker-compose build
```

### 2. Start core infra
```bash
docker-compose up -d nats mesh-registry autoscaler duckdb
```

### 3. Start intelligence layer
```bash
docker-compose up -d opencode openwolf composio
```

### 4. Start execution
```bash
docker-compose up -d n8n homeassistant
```

### 5. Verify system
```bash
curl http://localhost:7000/api/mesh
```

You should see 3 services registered (opencode, openwolf, composio).

---

## Testing Capability Routing

### Publish test event
```bash
docker exec ark-nats nats pub "ark.call.opencode.code.analyze" '{
  "request_id": "test-123",
  "params": {
    "source": "def foo(): pass",
    "language": "python"
  }
}'
```

### Subscribe to reply
```bash
docker exec ark-nats nats sub "ark.reply.test-123" &
```

You'll receive the agent response.

---

## Monitoring

### NATS Admin
```bash
docker exec ark-nats nats account info
docker exec ark-nats nats stream info ark.events
```

### Mesh Status
```bash
curl http://localhost:7000/api/mesh | jq
```

### Agent Logs
```bash
docker logs -f ark-opencode
docker logs -f ark-openwolf
docker logs -f ark-composio
```

---

## Scaling Behavior

### Example: High OpenCode Demand

1. **Workflow submits 50 code.generate requests**
2. **Queue depth published**: `ark.system.queue_depth.opencode = 50`
3. **Autoscaler threshold**: `queue_depth > 10`
4. **Decision**: Spawn new OpenCode instance
5. **Docker spawn**: `docker run ark-opencode:latest`
6. **Auto-register**: New instance publishes to `ark.mesh.register`
7. **Registry updates**: Capability routing now includes new instance
8. **Load balancing**: New requests routed to both instances
9. **Queue shrinks**: Requests complete, load normalizes
10. **Idle detection**: After 5 min of zero queue depth, instance terminates

---

## Hard Rules (System Contract)

✓ **No service has fixed address** — All services are ephemeral  
✓ **No direct TCP calls** — Everything via NATS  
✓ **All state in DuckDB** — Single source of truth  
✓ **Autoscaler is only spawn authority** — No manual service deployments  
✓ **Registry is only discovery** — No DNS/config files  
✓ **Capabilities define work** — Services register what they do, not where  
✓ **Heartbeat = health signal** — Expired services auto-removed  
✓ **Composio for external world** — No direct API calls from agents  

---

## ASHI (ARK System Health Index)

Computed by OpenWolf:

```
ASHI = 100 - (anomalies × 15)

Level mapping:
  90+ : Optimal
  70-89 : Good
  50-69 : Fair
  <50 : Critical
```

**Triggers autoscaler**: If ASHI < 60, may spawn recovery instances

---

## Environment Variables

### Mesh Registry
- `NATS_URL`: NATS connection (default: `nats://nats:4222`)

### Autoscaler
- `NATS_URL`: NATS connection
- `docker_sock`: Docker socket (default: `/var/run/docker.sock`)

### Agents
- `INSTANCE_ID`: Unique instance identifier (auto-generated if not set)
- `NATS_URL`: NATS connection
- `COMPOSIO_API_KEY`: (Composio bridge only) API key for external actions

---

## Architecture Benefits

### 1. **Self-routing compute**
Work is assigned dynamically via capability graph, not fixed routes

### 2. **Self-healing topology**
Failed services disappear, replacements spawn automatically

### 3. **Self-scaling behavior**
Load directly generates new instances (zero-config autoscaling)

### 4. **Externally coupled**
Composio turns ARK into an actuating system (not just internal compute)

### 5. **Auditable**
All events logged to DuckDB, full replay capability

### 6. **Observable**
Mesh registry provides real-time service inventory and health

---

## Next Steps

1. **Configure Composio**: Set `COMPOSIO_API_KEY` for external actions
2. **Build workflows in n8n**: Create event-driven automations
3. **Add domain agents**: Extend with finance-agent, inventory-agent, etc.
4. **Monitor ASHI**: Dashboard in Grafana
5. **Stress test**: Trigger high demand, watch autoscaler spawn instances
6. **Integrate IoT**: Connect MQTT → n8n → capabilities

---

**ARK is ready to evolve.**
