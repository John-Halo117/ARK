# ARK Deployment Guide

## Prerequisites

- Docker & Docker Compose installed
- 4GB+ RAM available
- Git

## Quick Deploy

### 1. Clone/Setup

```bash
# Assuming you have the ARK repo cloned
cd ark-os
```

### 2. Build Core Services

```bash
docker-compose build mesh-registry autoscaler opencode openwolf composio
```

Expected output:
```
Building mesh-registry  ... done
Building autoscaler    ... done
Building opencode      ... done
Building openwolf      ... done
Building composio      ... done
```

### 3. Start Infrastructure

```bash
docker-compose up -d nats mesh-registry autoscaler duckdb
```

Verify NATS is healthy:
```bash
docker logs ark-nats | grep "ready"
```

### 4. Start Intelligence Layer

```bash
docker-compose up -d opencode openwolf composio
```

Wait 5 seconds, then verify registration:
```bash
curl http://localhost:7000/api/mesh | python -m json.tool
```

Expected:
```json
{
  "services": 3,
  "instances": 3,
  "capabilities": 15,
  "service_details": {
    "opencode": { "instance_count": 1, "total_load": 0.0, "healthy_count": 1 },
    "openwolf": { "instance_count": 1, "total_load": 0.0, "healthy_count": 1 },
    "composio": { "instance_count": 1, "total_load": 0.0, "healthy_count": 1 }
  }
}
```

### 5. Start Execution Layer

```bash
docker-compose up -d n8n homeassistant
```

### 6. Optional: Observability

```bash
docker-compose up -d grafana meilisearch minio
```

---

## Verify System Operational

### Check All Services

```bash
docker-compose ps
```

All should show `Up`:
```
NAME                 STATUS
ark-nats             Up
ark-mesh             Up
ark-autoscaler       Up
ark-duckdb           Up
ark-opencode         Up
ark-openwolf         Up
ark-composio         Up
ark-n8n              Up
ark-homeassistant    Up
```

### Test Capability Routing

#### Subscribe to reply (in one terminal)
```bash
docker exec ark-nats nats sub "ark.reply.test-001" --raw
```

#### Trigger capability (in another terminal)
```bash
docker exec ark-nats nats pub "ark.call.opencode.code.analyze" \
'{"request_id":"test-001","params":{"source":"def foo(): pass","language":"python"}}'
```

You should see a response like:
```json
{
  "agent": "opencode",
  "instance_id": "opencode-0",
  "capability": "code.analyze",
  "language": "python",
  "analysis": { "lines": 1, "complexity": "medium", "issues": [] }
}
```

---

## Test Autoscaling

### 1. Monitor demand

```bash
watch -n 1 'curl -s http://localhost:7000/api/mesh | python -m json.tool | grep instance_count'
```

### 2. Generate high demand

```bash
# In new terminal, publish 100 events rapidly
for i in {1..100}; do
  docker exec ark-nats nats pub "ark.system.queue_depth.opencode" \
    "{\"depth\": 100, \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" &
done
wait
```

### 3. Observe scaling

Watch the command from step 1. You should see:
```
"instance_count": 1,  # Initial
"instance_count": 2,  # After first spawn
"instance_count": 3,  # If demand continues
```

Check spawned containers:
```bash
docker ps | grep ark-opencode
```

---

## Configure Composio (Optional)

To enable external action execution:

### 1. Get Composio API Key

Visit [Composio](https://composio.dev) and create an account

### 2. Set environment variable

```bash
export COMPOSIO_API_KEY=your_api_key_here
```

### 3. Restart Composio bridge

```bash
docker-compose restart composio
```

Verify:
```bash
docker logs ark-composio | grep "Composio"
```

---

## Monitor System Health

### Real-time Mesh Status

```bash
while true; do
  curl -s http://localhost:7000/api/mesh | python -m json.tool
  sleep 2
done
```

### View Agent Logs

```bash
# OpenCode activity
docker logs -f ark-opencode

# OpenWolf anomalies
docker logs -f ark-openwolf

# Mesh registry events
docker logs -f ark-mesh

# Autoscaler decisions
docker logs -f ark-autoscaler
```

### NATS Stream Inspection

```bash
# List streams
docker exec ark-nats nats stream ls

# View messages in a stream
docker exec ark-nats nats stream view ark.events --samples 10
```

---

## Shutdown

### Graceful shutdown

```bash
docker-compose down
```

### Full reset (including volumes)

```bash
docker-compose down -v
```

---

## Troubleshooting

### Services not registering

Check mesh registry:
```bash
docker logs ark-mesh | tail -20
```

Check agent connectivity:
```bash
docker logs ark-opencode | grep "Connected to NATS"
```

### High latency / slow responses

Check queue depth:
```bash
docker exec ark-nats nats stream view ark.events --samples 100
```

Trigger scaling:
```bash
docker exec ark-nats nats pub "ark.system.latency.opencode" \
'{"latency_ms": 5000}'
```

### DuckDB not initialized

Restart it:
```bash
docker-compose restart duckdb
sleep 5
```

### Port conflicts

Change ports in docker-compose.yml:
- NATS: 4222 → 4223 (and update NATS_URL env var)
- Mesh: 7000 → 7001
- Autoscaler: 7001 → 7002
- n8n: 5678 → 5679
- HA: 8123 → 8124

---

## Next Steps

1. **Create n8n workflows** using NATS-triggered events
2. **Configure Home Assistant** with actual devices
3. **Build domain agents** (finance, inventory, etc.)
4. **Set up dashboards** in Grafana
5. **Test failure scenarios** (kill containers, watch recovery)
6. **Deploy to production** (use Swarm or Kubernetes for multi-host)

---

## Production Considerations

### Multi-node Deployment

- Use Swarm or Kubernetes instead of docker-compose
- Replace NATS standalone with NATS cluster
- Replace DuckDB with PostgreSQL
- Add persistent volumes for all services
- Use external MQTT broker (not embedded)

### Security

- Run agents as non-root containers
- Use secrets management for API keys
- Add network policies between services
- Enable NATS authentication
- Use TLS for external connections

### Monitoring

- Set up Prometheus for metrics
- Add alerting rules for ASHI < 60
- Monitor queue depth trends
- Track spawn/terminate rates
- Log all capability calls to DuckDB

### Resource Limits

Add to docker-compose.yml:
```yaml
resources:
  limits:
    cpus: '1'
    memory: 1G
  reservations:
    cpus: '0.5'
    memory: 512M
```

---

**ARK is now running. Events flow. Services scale. Intelligence evolves.**
