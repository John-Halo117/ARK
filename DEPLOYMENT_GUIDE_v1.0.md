# ARK Production Deployment Guide v1.0

## Overview

ARK (Self-Scaling Event-Driven Operating System) is now production-ready with:
- Optimized multi-stage Docker builds for all services
- Production-grade docker-compose with resource limits
- GitHub Actions CI/CD with multi-arch builds (amd64/arm64)
- Forge two-way integration via NATS request/reply pattern
- Comprehensive health checks and monitoring

## Prerequisites

- Docker 24.0+
- Docker Compose 2.20+
- Git 2.40+
- 4GB RAM minimum (8GB recommended)
- Linux kernel 5.10+ (for full container features)

## Quick Start (Development)

```bash
# Clone repository
git clone https://github.com/John-Halo117/ARK.git
cd ARK

# Start stack
docker compose up -d

# Check health
curl http://localhost:8080/api/health
docker compose ps
```

## Production Deployment

### 1. Pre-Deployment Checklist

```bash
# Validate configuration
docker compose -f docker-compose.prod.yml config
docker buildx bake --print

# Run tests
pytest tests/ -v

# Check system resources
free -h
df -h /var/lib/docker
```

### 2. Build & Push Images

```bash
# Set registry (customize for your registry)
export ARK_REGISTRY=ghcr.io
export ARK_IMAGE_PREFIX=john-halo117/ark
export ARK_VERSION=v1.0

# Build for multi-arch (requires buildx)
docker buildx create --use
docker buildx bake --load

# Or push directly
docker buildx bake --push
```

### 3. Deploy to Production

```bash
# Set environment variables
export ENVIRONMENT=prod
export ARK_REGISTRY=ghcr.io
export ARK_IMAGE_PREFIX=john-halo117/ark
export ARK_VERSION=v1.0

# Create volumes and networks
docker volume create ark-nats
docker volume create ark-redis
docker volume create ark-duckdb
docker network create ark-net

# Start services
docker compose -f docker-compose.prod.yml up -d

# Verify deployment
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f gateway
```

### 4. Post-Deployment Verification

```bash
# Health checks
curl http://localhost:8080/api/health
curl http://localhost:7000/api/mesh
curl http://localhost:7001/api/health

# Service status
docker exec ark-gateway python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/api/status').read())"

# NATS status
docker exec ark-nats nats server info

# Event log check
curl 'http://localhost:8080/api/events?limit=10'
```

## Configuration

### Environment Variables

All services support configuration via `.env` file:

```env
# NATS
NATS_URL=nats://nats:4222

# Mesh Registry
ARK_GSB_ENABLED=1

# Autoscaler
ARK_AUTOSCALER_MIN_INSTANCES=1
ARK_AUTOSCALER_MAX_INSTANCES=10
ARK_AUTOSCALER_SCALE_UP_THRESHOLD=0.7
ARK_AUTOSCALER_SCALE_DOWN_THRESHOLD=0.2

# Stability Kernel
STABILITY_ALPHA_MAX=0.3
G_MAX=0.8
SIGMA_K=2.2

# Gateway
ARK_RATE_LIMIT_REQUESTS=100
ARK_RATE_LIMIT_WINDOW=60

# Data directory
ARK_CAS_ROOT=./data/cas
```

### Resource Limits (Production)

| Service | CPU | Memory |
|---------|-----|--------|
| NATS | 1.0 | 512M |
| Redis | 0.75 | 1G |
| DuckDB | 1.0 | 2G |
| Mesh | 1.0 | 768M |
| Autoscaler | 1.0 | 768M |
| Gateway | 1.0 | 1G |
| Stability-Kernel | 1.0 | 512M |
| Ingestion-Leader | 1.0 | 768M |

**Total: ~8 vCPU, ~7GB RAM**

## API Endpoints

### Health & Status

```bash
# Liveness probe
GET /api/health

# System status
GET /api/status

# Mesh status
GET /api/mesh

# Service info
GET /api/service/{name}
```

### Capability Routing

```bash
# Get routing for capability
GET /api/route/{capability}

# Call capability
POST /api/call/{capability}
{
  "request_id": "req-123",
  "params": {...}
}
```

### Data Queries

```bash
# List events
GET /api/events?source=X&type=Y&limit=100

# Get metrics
GET /api/metrics/{source}?limit=10
```

## Forge Integration

### Architecture

```
┌─────────────┐
│   Forge     │
│  Planner    │
└──────┬──────┘
       │ publishes to
       v
ark.call.{service}.{capability}
       │ NATS subject
       v
┌──────────────────┐
│  ARK Mesh        │
│  Registry        │ routes to best instance
└──────────────────┘
       │
       v
ark.service.instance
       │ processes request
       v
       │ replies to
       v
ark.reply.{request_id}
       │ NATS subject
       v
┌─────────────┐
│   Forge     │
│  Result     │ receives result
│  Sink       │
└─────────────┘
```

### Topics (NATS)

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `ark.forge.plan` | Forge → ARK | Planner publishes task |
| `ark.call.{service}.{capability}` | Forge → ARK | Capability request |
| `ark.reply.{request_id}` | ARK → Forge | Async response |
| `ark.forge.result` | ARK → Forge | Result sink |
| `ark.system.mesh` | ARK internal | Service registration |
| `ark.system.scale` | ARK internal | Scaling event |
| `ark.system.health` | ARK internal | Health updates |

### Example: Forge Calling OpenCode

```bash
# 1. Forge publishes capability call
nats pub "ark.call.opencode.code.analyze" '{
  "request_id": "req-001",
  "service": "opencode",
  "instance_id": "opencode-0",
  "capability": "code.analyze",
  "params": {
    "source": "def f(): pass",
    "language": "python"
  }
}'

# 2. OpenCode instance processes and replies
nats pub "ark.reply.req-001" '{
  "request_id": "req-001",
  "result": {"analysis": "..."},
  "timestamp": "2024-01-01T00:00:00Z"
}'

# 3. Forge receives result on subscription
nats sub "ark.reply.req-*"
```

## Monitoring & Observability

### Logs

```bash
# View all service logs
docker compose -f docker-compose.prod.yml logs -f

# View specific service
docker compose -f docker-compose.prod.yml logs -f gateway

# Query NATS events
docker exec ark-nats nats stream view ark.events --samples 100
```

### Metrics

```bash
# System stats
docker stats

# Service resource usage
docker compose -f docker-compose.prod.yml stats

# DuckDB metrics
curl http://localhost:8080/api/metrics/ark
```

### Health Checks

All services include built-in health checks:

```bash
# Manual health verification
docker exec ark-gateway python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"

docker exec ark-mesh python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7000/api/health')"

docker exec ark-stability-kernel wget -q -O - http://127.0.0.1:8081/health
```

## Scaling

### Manual Scaling

```bash
# View autoscaler configuration
docker compose -f docker-compose.prod.yml config | grep -A 10 "autoscaler:"

# Update min/max instances
docker compose -f docker-compose.prod.yml exec autoscaler \
  python -c "from ark.autoscaler import AUTOSCALER_CONFIG; print(AUTOSCALER_CONFIG)"
```

### Auto-Scaling

The autoscaler monitors queue depth and service health:

```bash
# View scaling events
docker compose -f docker-compose.prod.yml logs autoscaler | grep -i scale

# Trigger scaling by generating load
for i in {1..1000}; do
  curl -X POST http://localhost:8080/api/call/code.analyze \
    -H "Content-Type: application/json" \
    -d '{"params":{"source":"def f(): pass"}}' &
done
wait
```

## Backup & Recovery

### DuckDB Data

```bash
# Backup
docker compose -f docker-compose.prod.yml exec duckdb \
  tar -czf /data/backup-$(date +%s).tar.gz /data/ark.duckdb

# Restore
docker compose -f docker-compose.prod.yml exec duckdb \
  tar -xzf /data/backup-*.tar.gz
```

### NATS JetStream

```bash
# Backup state
docker compose -f docker-compose.prod.yml exec nats \
  nats stream backup ark.events /data/nats-backup

# Restore
docker compose -f docker-compose.prod.yml exec nats \
  nats stream restore /data/nats-backup
```

### Redis

```bash
# Backup
docker compose -f docker-compose.prod.yml exec redis \
  redis-cli BGSAVE

# Manual snapshot
docker volume inspect ark-redis
```

## Troubleshooting

### Service fails to start

```bash
# Check logs
docker compose -f docker-compose.prod.yml logs {service}

# Validate config
docker compose -f docker-compose.prod.yml config --format=json

# Test dependencies
docker compose -f docker-compose.prod.yml ps
```

### Health check failures

```bash
# Manual test
curl http://localhost:8080/api/health -v

# Check service endpoint
docker exec ark-gateway netstat -tlnp | grep 8080

# Verify network
docker network inspect ark-net
```

### High memory usage

```bash
# Check limits
docker compose -f docker-compose.prod.yml config | grep memory

# Monitor stats
docker stats --no-stream

# Increase limits in docker-compose.prod.yml
# Restart services:
docker compose -f docker-compose.prod.yml restart
```

### NATS connection issues

```bash
# Check NATS health
docker exec ark-nats nats server info

# Monitor connections
docker compose -f docker-compose.prod.yml logs nats | grep -i connection

# Reset NATS (warning: clears data)
docker compose -f docker-compose.prod.yml down -v
docker compose -f docker-compose.prod.yml up -d nats
```

## Cleanup

```bash
# Stop services
docker compose -f docker-compose.prod.yml down

# Remove volumes (WARNING: deletes data)
docker compose -f docker-compose.prod.yml down -v

# Remove images
docker rmi $(docker images | grep ark)

# Prune everything
docker system prune -a
```

## Security Considerations

### Network

- Run on isolated docker network (default: `ark-net`)
- Restrict access to ports via firewall
- Use firewall rules for production:

```bash
# Example iptables (Linux)
iptables -A INPUT -p tcp --dport 8080 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 8080 -j DROP
```

### Secrets Management

- Use `.env` file or Docker secrets in Swarm/Kubernetes
- Never commit `.env` to git
- Rotate API keys regularly

### Access Control

- NATS: Enable authentication in production
- API Gateway: Implement rate limiting (enabled by default)
- Use TLS termination proxy (nginx/Traefik)

## CI/CD Integration

### GitHub Actions

The `.github/workflows/ark-build-push.yml` workflow:

1. Lints code (ruff)
2. Runs tests (pytest)
3. Builds multi-arch images (buildx)
4. Pushes to registry (GHCR)
5. Validates compose config
6. Registers Forge callbacks

### Self-Hosted Runner

For production deployments to private infrastructure:

```bash
# Add runner to repository
Settings → Actions → Runners → New self-hosted runner

# Install runner
./config.sh --url https://github.com/{org}/{repo} --token {TOKEN}

# Run as service
sudo ./svc.sh install
sudo ./svc.sh start
```

## Support & Resources

- **Architecture**: See `ARK_SPEC.md`
- **TRISCA**: See `TRISCA.md`
- **Forge**: See `FORGE_START_HERE.md`
- **Quick Commands**: See `QUICK_REFERENCE.md`

---

**ARK v1.0 is production-ready. Deploy with confidence.**
