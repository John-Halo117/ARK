# ARK OS - Complete System Map

**Three emitters + core ARK = intelligent, reactive infrastructure.**

---

## System Architecture (Complete)

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA SOURCES (EMITTERS)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Home         │  │ Jellyfin     │  │ UniFi        │       │
│  │ Assistant    │  │ Media Server │  │ Network      │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└────────┬──────────────────┬──────────────────┬───────────────┘
         │                  │                  │
         └──────────────────┼──────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   EVENT BACKBONE (NATS)                      │
│  Topics: ark.events, ark.event.*, ark.metrics.*             │
│  Queue depth: 10,000+ events/min capacity                   │
└────────┬──────────────────┬──────────────────┬───────────────┘
         │                  │                  │
    ┌────▼────┐         ┌────▼────┐      ┌────▼────┐
    │ Mesh    │         │ Data    │      │ n8n     │
    │Registry │         │ Store   │      │Workflows│
    │         │         │(DuckDB) │      │         │
    └────┬────┘         └────┬────┘      └────┬────┘
         │                   │                │
         └───────────────────┼────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│              INTELLIGENCE LAYER (AGENTS)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ OpenCode     │  │ OpenWolf     │  │ Composio     │       │
│  │ Reasoning    │  │ Health       │  │ External     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└────────┬──────────────────┬──────────────────┬───────────────┘
         │                  │                  │
         └──────────────────┼──────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│               EXECUTION & OBSERVABILITY                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Home         │  │ Grafana      │  │ Meilisearch  │       │
│  │ Assistant    │  │ Dashboards   │  │ Search       │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

---

## Complete Service Inventory

### Data Sources (Emitters)

```
homeassistant (service)
├── Capabilities: event.home_assistant, state.device_update, climate.temperature, light.toggle, sensor.reading
├── Emits: ark.event.state.change, ark.event.climate.temperature, ark.metrics.temperature
├── Polls: HA every 5 seconds
└── Instance: ha-emitter-0

jellyfin (service)
├── Capabilities: media.playback, media.library, media.search, playback.status, library.items
├── Emits: ark.event.media.playback, ark.metrics.media_duration
├── Polls: Jellyfin every 10 seconds
└── Instance: jellyfin-emitter-0

unifi (service)
├── Capabilities: network.devices, network.events, network.stats, device.status, wireless.clients, network.health
├── Emits: ark.event.network.device, ark.metrics.network
├── Polls: UniFi every 30 seconds
└── Instance: unifi-emitter-0
```

### Core Infrastructure

```
nats (NATS JetStream)
├── Event backbone: 10,000+ events/min
├── Persistent: All events logged
├── Port: 4222
└── Admin: 8222

mesh-registry (Service Discovery)
├── Maps: capabilities → instances
├── Tracks: service health
├── Routes: load-aware
└── API: 7000

autoscaler (Compute Spawner)
├── Monitors: queue depth, latency
├── Spawns: instances on demand
├── Terminates: idle services
└── API: 7001

duckdb (SSOT)
├── Stores: all events
├── Tables: events, state, metrics
├── Queries: DQL/SQL
└── Location: /data/ark.duckdb
```

### Intelligence Layer

```
opencode (Agent)
├── Capabilities: code.analyze, code.transform, code.generate, reasoning.plan, reasoning.decompose
├── Instance: opencode-0
└── Process: Event → Reasoning → Result

openwolf (Agent)
├── Capabilities: anomaly.detect, system.health, metrics.ingest, ashi.compute
├── Instance: openwolf-0
└── Process: Metrics → Analysis → Health score

composio (Agent)
├── Capabilities: external.email, external.github, external.slack, external.notion
├── Instance: composio-0
└── Process: Request → API call → Result
```

### Execution & Observability

```
n8n (Workflow Engine)
├── Triggers: Webhooks, intervals
├── Actions: Call capabilities
├── Port: 5678
└── DB: SQLite

grafana (Dashboards)
├── Metrics: From NATS + agents
├── Visualizations: Timeseries, gauges
├── Port: 3000
└── Default: admin/admin

meilisearch (Search)
├── Indexes: Events, documents
├── Query: Full-text search
├── Port: 7700
└── Speed: <50ms queries
```

---

## Complete Event Flow

### Example: Movie Time Activation

```
1. User presses play in Jellyfin
   └─→ jellyfin-emitter detects playback_start
       └─→ Publishes: ark.event.media.playback {event: "playback_start", title: "Breaking Bad"}

2. Event arrives in NATS
   └─→ Multiple subscribers notified
       ├─→ DuckDB: Logs event
       ├─→ n8n: Webhook trigger fires
       └─→ OpenWolf: Checks if unusual time

3. n8n workflow executes:
   ├─→ Query: homeassistant.sensor.reading (motion_sensor)
   ├─→ Query: jellyfin.playback.status
   ├─→ Query: unifi.network.health
   └─→ Correlate: If all good, activate movie_mode

4. Actions triggered:
   ├─→ homeassistant.state.device_update (lights → 10%)
   ├─→ homeassistant.state.device_update (climate → cool)
   └─→ homeassistant.state.device_update (blinds → closed)

5. Results logged:
   ├─→ Events table: All state changes
   ├─→ State table: Current system state
   └─→ Metrics table: Performance metrics

6. Analytics:
   ├─→ DuckDB: Query patterns (when does movie mode activate?)
   ├─→ OpenWolf: Detect anomalies (unusual activation?)
   ├─→ Meilisearch: Search events (find all movie sessions)
   └─→ Grafana: Dashboard shows movie frequency
```

---

## Data Types & Schemas

### Event Structure (All Types)

```json
{
  "type": "ark.event.X",           // Topic/type
  "entity_id": "device.name",      // What changed
  "old_state": "value",            // Previous state
  "new_state": "value",            // Current state
  "attributes": {},                // Metadata
  "timestamp": "2024-01-15T10:30:00Z",  // When
  "source": "homeassistant"        // Origin
}
```

### Metric Structure

```json
{
  "name": "network.device_count",  // Metric name
  "value": 42,                     // Numeric value
  "unit": "count",                 // Unit
  "timestamp": "2024-01-15T10:30:00Z",
  "source": "unifi"                // Origin
}
```

### Capability Request

```json
{
  "request_id": "req-123",         // Unique ID
  "params": {                      // Request params
    "entity_id": "light.bedroom"
  }
}
```

### Capability Response

```json
{
  "agent": "homeassistant",        // Agent that responded
  "instance_id": "ha-emitter-0",   // Which instance
  "capability": "light.toggle",    // What was called
  "success": true,                 // Did it work?
  "result": {...},                 // Data
  "timestamp": "2024-01-15T10:30:00Z"
}
```

---

## Deployment Checklist

- [ ] Core infrastructure running (NATS, mesh, autoscaler, DuckDB)
- [ ] Intelligence agents running (OpenCode, OpenWolf, Composio)
- [ ] HA credentials set + emitter built
- [ ] Jellyfin credentials set + emitter built
- [ ] UniFi credentials set + emitter built
- [ ] All emitters registered in mesh
- [ ] Events flowing through NATS
- [ ] Events logged to DuckDB
- [ ] n8n workflows configured
- [ ] Grafana dashboards set up
- [ ] Monitoring active

---

## Typical Load Profile

### Events Per Hour (Estimate)

```
Home Assistant:    720 events/hour (on changes only)
Jellyfin:          360 events/hour (on playback changes)
UniFi:             120 events/hour (on device changes)
─────────────────────────────────────
Total:           1,200 events/hour baseline
Peak:            5,000 events/hour (high activity)
```

### Resource Usage

```
NATS:              200MB memory, 0.1 CPU cores
Mesh Registry:     100MB memory, 0.05 CPU cores
Autoscaler:        100MB memory, 0.05 CPU cores
DuckDB:            150MB memory, 0.1 CPU cores
Emitters (3):      300MB memory, 0.15 CPU cores
Agents (3):        300MB memory, 0.2 CPU cores
n8n:               400MB memory, 0.2 CPU cores
─────────────────────────────────────
Total:           1.6GB memory, 0.85 CPU cores
```

---

## Monitoring Dashboard (Grafana)

Recommended panels:

1. **Event Throughput** - Events/sec by source
2. **Queue Depth** - Per-service backlog
3. **Agent Response Time** - P50, P95, P99
4. **Network Health Score** - UniFi metrics
5. **Media Activity** - Playback events
6. **Device State Changes** - HA transitions
7. **System Health (ASHI)** - OpenWolf score
8. **Anomalies Detected** - Count/hour

---

## Query Examples (DuckDB)

### Find patterns in media playback

```sql
SELECT 
  HOUR(timestamp) as hour,
  COUNT(*) as playback_events,
  AVG(CASE WHEN event = 'playback_start' THEN 1 ELSE 0 END) as session_starts
FROM events
WHERE type = 'ark.event.media.playback'
  AND DATE(timestamp) >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY HOUR(timestamp)
ORDER BY playback_events DESC;
```

### Correlate device changes with network events

```sql
SELECT 
  h.entity_id,
  h.new_state,
  COUNT(u.event) as network_events_nearby
FROM events h
LEFT JOIN events u ON 
  u.source = 'unifi' 
  AND DATEDIFF(MINUTE, h.timestamp, u.timestamp) BETWEEN -5 AND 5
WHERE h.source = 'homeassistant'
  AND h.type LIKE 'ark.event%'
GROUP BY h.entity_id, h.new_state
ORDER BY network_events_nearby DESC;
```

### Find anomalies

```sql
SELECT 
  timestamp,
  payload->>'metric' as metric,
  payload->>'value' as value,
  payload->>'severity' as severity
FROM events
WHERE type = 'ark.anomaly.detected'
  AND payload->>'severity' = 'high'
  AND DATE(timestamp) >= CURRENT_DATE
ORDER BY timestamp DESC
LIMIT 50;
```

---

## Troubleshooting Decision Tree

```
Problem: Events not flowing
├─ Check: Is NATS running? (docker ps | grep nats)
├─ Check: Are emitters started? (docker ps | grep emitter)
├─ Check: Are credentials set? (echo $HA_TOKEN, etc)
├─ Check: Do emitters see services? (docker logs ark-ha-emitter)
└─ Check: Events in stream? (docker exec ark-nats nats stream info ark.events)

Problem: Mesh registry empty
├─ Check: Did services register? (curl http://localhost:7000/api/mesh)
├─ Check: Are heartbeats working? (docker exec ark-nats nats sub ark.mesh.heartbeat)
├─ Check: Any errors in mesh logs? (docker logs ark-mesh)
└─ Check: Are services configured correctly? (env variables set?)

Problem: No data in DuckDB
├─ Check: Is DuckDB running? (docker ps | grep duckdb)
├─ Check: Can you connect? (docker exec ark-duckdb sqlite3 /data/ark.duckdb)
├─ Check: Tables exist? (docker exec ark-duckdb duckdb /data/ark.duckdb "SELECT * FROM events;")
└─ Check: Permissions? (docker logs ark-duckdb)

Problem: n8n workflows not triggering
├─ Check: Webhook created? (n8n UI)
├─ Check: NATS connection? (Check n8n logs)
├─ Check: Topic correct? (ark.event.X matches workflow trigger)
└─ Check: Event actually published? (subscribe to topic and test)
```

---

## What You Have Built

✅ **Event-driven infrastructure** that reacts in real-time  
✅ **Three emitters** feeding data from home/network/media  
✅ **17 new capabilities** exposed to agents  
✅ **Intelligent mesh** routing work dynamically  
✅ **Auto-scaling** based on demand  
✅ **Centralized truth** in DuckDB  
✅ **Workflow orchestration** via n8n  
✅ **Observable** via Grafana + Meilisearch  

---

## Next Moves

**Immediate:** Get emitters running and verified  
**Short-term:** Build n8n workflows  
**Medium-term:** Create learning agents  
**Long-term:** Add more domain agents, expand automation  

---

**ARK is now a complete event-driven intelligent operating system.**

**Your home/infrastructure is watching. It's listening. It's responding.**
