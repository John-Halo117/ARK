# ARK System - Complete Port & URL Reference

## CORE INFRASTRUCTURE
| Service | Port | URL |
|---------|------|-----|
| NATS | 4222 | nats://localhost:4222 |
| NATS Monitoring | 8222 | http://localhost:8222 |
| Mesh Registry | 7000 | http://localhost:7000/api/mesh |
| Autoscaler | 7001 | http://localhost:7001 |
| DuckDB | 7777 | http://localhost:7777 |
| **API Gateway** | **8080** | **http://localhost:8080** ⭐ |

## INTELLIGENCE LAYER
| Service | Port | URL |
|---------|------|-----|
| OpenCode | 6001 | http://localhost:6001 |
| OpenWolf | 6002 | http://localhost:6002 |
| Composio | 6003 | http://localhost:6003 |

## DATA EMITTERS
| Service | Port | URL |
|---------|------|-----|
| HA Emitter | 6010 | http://localhost:6010 |
| Jellyfin Emitter | 6011 | http://localhost:6011 |
| UniFi Emitter | 6012 | http://localhost:6012 |

## EXECUTION LAYER
| Service | Port | URL |
|---------|------|-----|
| n8n | 5678 | http://localhost:5678 |
| Home Assistant | 8123 | http://localhost:8123 |
| Jellyfin | 8096 | http://localhost:8096 |
| UniFi Controller | 8443 | https://localhost:8443 |

## STORAGE & OBSERVABILITY
| Service | Port | URL |
|---------|------|-----|
| MinIO API | 9000 | http://localhost:9000 |
| MinIO Console | 9001 | http://localhost:9001 |
| Grafana | 3000 | http://localhost:3000 |
| Meilisearch | 7700 | http://localhost:7700 |

## ANALYSIS ENGINE
| Service | Port | URL |
|---------|------|-----|
| ARK Core (Rust) | 9999 | http://localhost:9999 |

---

## API GATEWAY ENDPOINTS (Primary Entry Point)

```
GET  http://localhost:8080/api/status              # System health
GET  http://localhost:8080/api/mesh                # Mesh registry status
GET  http://localhost:8080/api/service/{name}      # Service details
GET  http://localhost:8080/api/route/{capability}  # Find best instance
POST http://localhost:8080/api/call/{capability}   # Execute capability
GET  http://localhost:8080/api/events              # Query events
GET  http://localhost:8080/api/metrics/{source}    # Get LKS metrics
```

## DASHBOARD ACCESS

| Dashboard | URL | Credentials |
|-----------|-----|-------------|
| Grafana | http://localhost:3000 | admin / admin |
| n8n | http://localhost:5678 | (first run setup) |
| Home Assistant | http://localhost:8123 | (first run setup) |
| Jellyfin | http://localhost:8096 | (first run setup) |
| MinIO | http://localhost:9001 | minioadmin / minioadmin |
| UniFi | https://localhost:8443 | (first run setup) |

---

## TOTAL DEPLOYMENT

- **25 Services**
- **27 Published Ports**
- **1 Primary Gateway** (http://localhost:8080)
- **Unified Event Schema** (Python + Rust)
- **DuckDB SSOT** (Single Source of Truth)
- **NATS Event Backbone**
- **Full Mesh Discovery**

## START HERE

```bash
# 1. Start core stack
docker-compose up -d nats mesh-registry autoscaler duckdb gateway

# 2. Check status
curl http://localhost:8080/api/status

# 3. View mesh
curl http://localhost:8080/api/mesh

# 4. Start all (optional - includes large images)
docker-compose up -d
```
