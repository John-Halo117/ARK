## WIRING CHECKLIST - What You Need To Do

### ✅ COMPLETED (Pushed to GitHub)
1. **Event Schema** (`ark/event_schema.py`) — Unified format for Python/Rust
2. **DuckDB Client** (`ark/duck_client.py`) — Python agents can now query/write DuckDB
3. **API Gateway** (`ark/api_gateway.py`) — Single entry point at port 8080
4. **Dockerfiles** — `Dockerfile.ark` (Rust binary) + `Dockerfile.gateway` (Python gateway)
5. **Healthchecks** — NATS, Mesh, Autoscaler now have proper liveness probes
6. **Event Publishing** — Mesh registry already publishes to NATS topics

### 🔧 YOU MUST DO NOW

#### 1. **MERGE docker-compose-additions.yml**
Copy the gateway + ark services from `docker-compose-additions.yml` into `docker-compose.yml`:

```bash
# After the unifi-emitter service, before the "networks:" section, add:

  # CORE INFRA - API Gateway
  gateway:
    build:
      context: .
      dockerfile: Dockerfile.gateway
    container_name: ark-gateway
    environment:
      NATS_URL: nats://nats:4222
      MESH_URL: http://ark-mesh:7000
      PYTHONUNBUFFERED: "1"
    ports:
      - "8080:8080"
    depends_on:
      mesh-registry:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8080/api/status"]
      interval: 10s
      timeout: 5s
      retries: 3
    networks:
      - ark-net

  # ANALYSIS - Rust ARK Core
  ark:
    build:
      context: .
      dockerfile: Dockerfile.ark
    container_name: ark-core
    environment:
      RUST_LOG: info
    depends_on:
      duckdb:
        condition: service_started
      nats:
        condition: service_healthy
    networks:
      - ark-net
```

#### 2. **CREATE ark/Cargo.lock**
Run this in your ark/ directory:
```bash
cd ark
cargo generate-lockfile
```
(This ensures reproducible builds)

#### 3. **TEST LOCALLY (optional)**
```bash
cd ark
cargo build --release
./target/release/ark
```

#### 4. **BUILD & TEST FULL STACK**
```bash
# Clean up old containers
docker-compose down

# Build all images (first time will take ~2 min)
docker-compose build

# Start core services only (avoid large images)
docker-compose up -d nats mesh-registry autoscaler duckdb opencode openwolf composio gateway ark

# Verify
docker ps --filter "name=ark-" --format "table {{.Names}}\t{{.Status}}"

# Check gateway is healthy
curl http://localhost:8080/api/status

# Check mesh has registered services
curl http://localhost:8080/api/mesh
```

#### 5. **VERIFY INTEGRATION** (Test wiring works end-to-end)

**Test 1 — Call a capability:**
```bash
curl -X POST http://localhost:8080/api/call/code.analyze \
  -H "Content-Type: application/json" \
  -d '{
    "params": {
      "source": "def foo(): pass",
      "language": "python"
    }
  }'
```

**Test 2 — Query events (should be empty initially):**
```bash
curl http://localhost:8080/api/events
```

**Test 3 — Check Rust ARK is running:**
```bash
docker logs ark-core
```
Should see: `ARK v1.0 core + Δ + DuckDB + Kalman running`

---

### ⚠️ IMPORTANT - YOU NEED TO PROVIDE

**❓ For Rust build to work**, I need to know:

1. **Do you have Cargo.lock in ark/?** 
   - If not, I'll auto-generate it

2. **Do you want the Rust ARK to run as a daemon or batch?**
   - Current: 100-iteration batch then exits
   - Could be: continuous daemon listening to NATS

3. **Should ARK core subscribe to events from NATS?**
   - Currently processes hardcoded test data
   - Should it: read from `ark.events.*` topic instead?

---

### 🎯 NEXT STEPS AFTER WIRING

Once everything is wired:

1. **Emit real events** — Configure emitters (HA, Jellyfin, UniFi) with credentials
2. **Process events** — ARK reads from NATS, computes LKS, stores to DuckDB
3. **Query results** — Use gateway `/api/metrics/{source}` to see computed metrics
4. **Build automations** — n8n workflows trigger based on DSS thresholds
5. **Monitor system** — Grafana dashboards querying DuckDB

---

### 📊 DATA FLOW (After Wiring Complete)

```
Emitters (HA/Jellyfin/UniFi)
    ↓ (NATS: ark.event.*)
Agents (OpenCode/OpenWolf/Composio)
    ↓ (Process)
Rust ARK Core (TRISCA + Kalman + Delta)
    ↓ (DuckDB: store LKS + delta)
API Gateway (REST: /api/metrics, /api/events)
    ↓
n8n / Grafana / Queries
```

---

### QUESTIONS FOR YOU

1. **Rust binary architecture** — Should ARK listen on NATS topics continuously, or run once per minute?
2. **Emitter credentials** — Do you have HA token, Jellyfin token, UniFi credentials ready?
3. **Priority** — What's more important: get gateway working first, or get Rust ARK processing events?

**Once you answer, I'll wire up the remaining pieces.**
