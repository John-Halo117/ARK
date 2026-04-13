# ARK System - All Published Ports

## Core Infrastructure
| Service | Port | Purpose |
|---------|------|---------|
| NATS | 4222 | Event messaging (core) |
| NATS Monitoring | 8222 | Health/metrics endpoint |
| Mesh Registry | 7000 | Service discovery API |
| Autoscaler | 7001 | Dynamic compute control |
| DuckDB | 7777 | Database stub (internal) |
| API Gateway | 8080 | ⭐ **Main entry point** |

## Intelligence Layer (Agents)
| Service | Port | Purpose |
|---------|------|---------|
| OpenCode | 6001 | Reasoning/code analysis |
| OpenWolf | 6002 | Health monitoring |
| Composio | 6003 | External tool integration |

## Data Emitters
| Service | Port | Purpose |
|---------|------|---------|
| HA Emitter | 6010 | Home Assistant events |
| Jellyfin Emitter | 6011 | Media server events |
| UniFi Emitter | 6012 | Network monitoring |

## Execution Layer
| Service | Port | Purpose |
|---------|------|---------|
| n8n | 5678 | Workflow automation |
| Home Assistant | 8123 | IoT control + UI |
| Jellyfin | 8096 | Media server |
| UniFi Controller | 8080, 8443 | Network management |

## Storage & Observability
| Service | Port | Purpose |
|---------|------|---------|
| MinIO Console | 9001 | S3 storage UI |
| MinIO API | 9000 | S3 API |
| Grafana | 3000 | Dashboards |
| Meilisearch | 7700 | Search engine |

## Rust ARK Core
| Service | Port | Purpose |
|---------|------|---------|
| ARK | 9999 | Reserved for future metrics |

---

## Quick Access

**Start here:** http://localhost:8080/api/status

**API endpoints:**
- Mesh status: `GET http://localhost:8080/api/mesh`
- Query events: `GET http://localhost:8080/api/events?source=X`
- Get metrics: `GET http://localhost:8080/api/metrics/{source}`
- Call capability: `POST http://localhost:8080/api/call/{capability}`

**Dashboards:**
- Grafana: http://localhost:3000 (admin/admin)
- n8n: http://localhost:5678
- Home Assistant: http://localhost:8123
- Jellyfin: http://localhost:8096
- MinIO: http://localhost:9001

**Direct Services:**
- NATS: nats://localhost:4222
- Mesh API: http://localhost:7000/api/mesh
- Meilisearch: http://localhost:7700
