# ARK Quick Reference

## Start System

```bash
docker-compose build mesh-registry autoscaler opencode openwolf composio
docker-compose up -d
```

## Check Status

```bash
curl http://localhost:7000/api/mesh | jq
```

Expected output:
```json
{
  "services": 3,
  "instances": 3,
  "capabilities": 15
}
```

## Service URLs

| Service | URL | Port |
|---------|-----|------|
| NATS | nats://localhost:4222 | 4222 |
| Mesh Registry API | http://localhost:7000 | 7000 |
| Autoscaler API | http://localhost:7001 | 7001 |
| n8n | http://localhost:5678 | 5678 |
| Home Assistant | http://localhost:8123 | 8123 |
| Grafana | http://localhost:3000 | 3000 |
| MinIO Console | http://localhost:9001 | 9001 |
| Meilisearch | http://localhost:7700 | 7700 |

## Test Capability Routing

**Terminal 1** (subscribe to reply):
```bash
docker exec ark-nats nats sub "ark.reply.test-001" --raw
```

**Terminal 2** (publish request):
```bash
docker exec ark-nats nats pub "ark.call.opencode.code.analyze" \
'{"request_id":"test-001","params":{"source":"def foo(): pass","language":"python"}}'
```

Expected reply from Terminal 1:
```json
{"agent":"opencode","instance_id":"opencode-0","capability":"code.analyze",...}
```

## Monitor Logs

```bash
docker logs -f ark-mesh          # Registry events
docker logs -f ark-autoscaler    # Scaling decisions
docker logs -f ark-opencode      # Code agent activity
docker logs -f ark-openwolf      # Health monitoring
docker logs -f ark-composio      # External actions
```

## Scale Test

```bash
for i in {1..50}; do
  docker exec ark-nats nats pub "ark.system.queue_depth.opencode" \
    "{\"depth\": 100, \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" &
done
wait
```

Then check spawned instances:
```bash
docker ps | grep ark-opencode
```

## NATS Inspection

```bash
# Stream info
docker exec ark-nats nats stream info ark.events

# View messages (last 10)
docker exec ark-nats nats stream view ark.events --samples 10

# List accounts
docker exec ark-nats nats account info
```

## Mesh API Endpoints

```bash
# Full mesh status
curl http://localhost:7000/api/mesh

# Route capability
curl http://localhost:7000/api/route/code.analyze

# Service details
curl http://localhost:7000/api/service/opencode

# Autoscaler: get instances
curl http://localhost:7001/api/instances/opencode

# Autoscaler: spawn instance
curl -X POST http://localhost:7001/api/spawn \
  -d '{"service":"opencode"}' \
  -H "Content-Type: application/json"
```

## Container Management

```bash
# All running
docker-compose ps

# Stop all
docker-compose stop

# Down (keeps volumes)
docker-compose down

# Down (remove everything)
docker-compose down -v

# Rebuild one service
docker-compose build mesh-registry
docker-compose up -d mesh-registry

# Logs
docker-compose logs -f
docker-compose logs -f opencode
```

## Environment Variables

Set before `docker-compose up`:
```bash
export COMPOSIO_API_KEY=your_api_key
export NATS_URL=nats://nats:4222
export INSTANCE_ID=custom-id
```

## Common Issues

### Services not registering
```bash
docker logs ark-opencode | grep "Connected to NATS"
```

### High latency
```bash
docker exec ark-nats nats stream view ark.events --samples 100 | grep -c "data:"
```

### Port conflicts
Edit docker-compose.yml and change ports:
- NATS: 4222 → 4223
- Mesh: 7000 → 7001
- Autoscaler: 7001 → 7002
- n8n: 5678 → 5679
- HA: 8123 → 8124

### DuckDB not ready
```bash
docker-compose restart duckdb
sleep 5
```

## Add Custom Agent

1. Create `/agents/my-agent/agent.py` (use template from EXAMPLES.md)
2. Create `Dockerfile.myagent`
3. Add to docker-compose.yml
4. Build & start: `docker-compose build myagent && docker-compose up -d myagent`

## Performance Tuning

### Increase agent instances (docker-compose.yml)

Find in `services` section and add multiple entries:
```yaml
opencode-0:
  ...
opencode-1:
  ...
opencode-2:
  ...
```

### Increase queue threshold (ark/autoscaler.py)

Edit:
```python
"opencode": {
  "queue_threshold": 10,  # Lower = spawn more aggressively
}
```

### Monitor metrics (Grafana)

1. Add NATS data source: `http://localhost:8222`
2. Create dashboard with:
   - Event throughput
   - Queue depth per service
   - Response latency
   - Instance count

## Backup & Recovery

```bash
# Backup DuckDB
docker run --rm -v duckdb_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/duckdb.tar.gz /data

# Restore DuckDB
docker run --rm -v duckdb_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/duckdb.tar.gz
```

## Production Checklist

- [ ] Set `COMPOSIO_API_KEY` env var
- [ ] Configure resource limits in docker-compose.yml
- [ ] Set up external logging (ELK, Loki)
- [ ] Configure Grafana alerts
- [ ] Test autoscaling under load
- [ ] Verify DuckDB backups
- [ ] Document runbooks
- [ ] Setup monitoring dashboards
- [ ] Enable authentication (NATS, Mesh API)
- [ ] Configure TLS for external APIs

---

**ARK is operational. Use these commands for daily operations.**
