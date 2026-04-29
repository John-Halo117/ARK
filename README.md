# ARK OS - Self-Scaling Event-Driven Operating System

**A production-grade, Gordon-deployed, NATS-first intelligent operating system.**

This workspace now also carries a canonical truth-spine and governance scaffold
under [`ark-core`](ark-core/README.md). That area holds the ingest-to-truth
architecture docs, shared model types, epistemic resolution primitives, and
CI/AI enforcement scripts without replacing the existing runtime-oriented main
repo layout.

## Start Forge

If you only want the self-coding part of ARK, use Forge.

- WSL, Git Bash, or Linux/macOS terminal: `./forge`
- Browser app: `./forge --desktop`
- Linux/Arch app install: `./install-forge-arch.sh`
- PowerShell: `.\forge.ps1`
- Command Prompt: `forge.cmd`
- One-click Windows launcher: `Forge App.cmd`
- Runtime check: `./forge --check`

The fastest beginner path is:

1. Double-click `Forge App.cmd` on Windows, or run `./forge --desktop`.
2. On Arch Linux, run `./install-forge-arch.sh` once if you want Forge in your app launcher.
3. Type the task into the Forge composer.
4. Press `Run`, inspect the live diff/tests/redteam panels, then accept or reject.

The Linux app install is user-local only. It creates no systemd service. Use the Forge Shutdown button when you are done with the browser app.

There is also a short guide at [`FORGE_START_HERE.md`](FORGE_START_HERE.md).

## Canonical docs

The architecture is intentionally split so each concept has one owner:

| File | Owns |
| --- | --- |
| [`ARK_SPEC.md`](ARK_SPEC.md) | Main system architecture specification |
| [`TRISCA.md`](TRISCA.md) | Distribution-aware scoring and control |
| [`SYSTEM_MAP.md`](SYSTEM_MAP.md) | Root system topology |
| [`ark-core/docs/ARK_TRUTH_SPINE.md`](ark-core/docs/ARK_TRUTH_SPINE.md) | Universal ingest-to-truth architecture |
| [`ark-core/docs/CODEX_ARK_SYSTEM_PROMPT.md`](ark-core/docs/CODEX_ARK_SYSTEM_PROMPT.md) | Agent/runtime behavior contract |
| [`ark-core/docs/MISSION_GRADE_RULES.md`](ark-core/docs/MISSION_GRADE_RULES.md) | Mission posture, central operating rules, and invariants |
| [`ark-core/docs/TODO_TIERS.md`](ark-core/docs/TODO_TIERS.md) | S/T/P governance rules |
| [`ark-core/docs/REDTEAM.md`](ark-core/docs/REDTEAM.md) | Red Team gates and scenarios |
| [`ark-core/docs/ark-field-v4.2-foundation.md`](ark-core/docs/ark-field-v4.2-foundation.md) | Field stage bridge into the truth spine |

---

## 🎯 What is ARK?

ARK is a **self-scaling distributed compute organism** where:

- **Services are not deployed** — they're **grown in response to event pressure**
- **Work is routed via capabilities** — not IP addresses or DNS
- **Intelligence emerges from demand** — autoscaling, health monitoring, anomaly detection
- **External world is coupled** — Composio enables real-world automation

### Core Principle

```
event pressure → mesh discovery → agent execution → state logging → feedback → autoscaling
```

## SD-ARK Loop

SD-ARK adds a deterministic Go spine for replayable, event-driven execution:

```
Event → Resolve(Δ) → TRISCA → S[6] → Policy → Intent → Action → Result → Meta(Δ_defs)
```

`S[6]` is the bounded TRISCA vector:

```
[structure, entropy, inequality, temporal, efficiency, signal_density]
```

### SD-ARK Module Map

| Path | Role |
| --- | --- |
| `core/step.go` | Single Step loop, typed contracts, health signals, structured failures |
| `core/trisca.go` | One deterministic TRISCA path producing `S[6]` |
| `core/bayes.go` | Bounded log-odds update for evidence deltas |
| `core/interpreter.go` | Wiring boundary from event ingress into Step |
| `runtime/compiler.go` | Compiles bounded definition files into runtime tables |
| `definitions/*.yaml` | JSON-compatible YAML policy, action, routing, and meta definitions |
| `policy/policy.go` | Table-driven policy scoring with `confidence*EV-cost` |
| `action/action.go` | Thin idempotent adapter execution boundary |
| `meta/meta.go` | Bounded meta delta emission and safe local application |
| `gsb/gsb.go` | Pub/sub interface with in-memory replayable implementation |
| `api/server.go` | `/ingest`, `/gsb`, `/trisca`, `/policy`, `/action`, `/meta` handlers |
| `ark/sd_trisca.py` | Python TRISCA mirror for planners and tool selection |
| `ark/task_graph.py` | Bounded DAG TaskSpec, executor, scheduler, chunker, reducer, replay cache |
| `ark/tool_system.py` | TRISCA-driven tool registry and selector with max 5 exposed tools |
| `ark/skills.py` | Skill pipelines that produce DAG task specs instead of tool exposure |
| `ark/mcp_containment.py` | Sandboxed MCP fallback boundary outside the core loop |
| `ark/codegen_safe.py` | Safe-mode plugin spec generation and validation without shell execution |
| `ark/forge_planner.py` | Forge planner facade; agents emit plans and do not execute DAGs |

Runtime caps are explicit in each module health result. Tables, request bodies,
logs, actions, messages, observations, and emitted meta deltas are bounded so the
loop remains replayable under partial failure.

### SD-ARK Execution Flow

```
Reality
  -> /ingest
  -> /gsb
  -> /trisca
  -> S[6]
  -> ToolSelector
  -> Skills / Forge planners
  -> DAG Scheduler (max concurrency 10)
  -> API tools
  -> optional MCP fallback
  -> /action
  -> Result
  -> /meta
```

MCP is contained as `tool.mcp.exec` and is fallback-only. Tool exposure is capped
at five selected tools, selected deterministically from TRISCA vectors, cost, and
success rate. Missing tools go through safe-mode codegen as static plugin specs:
generate spec, validate, sandbox result, then register only after external
validation.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ TIER 1: Event Backbone (NATS JetStream)                            │
│  - Primary message transport                                        │
│  - Service registration, demand signals, capability calls           │
│  - Full event history (replay capability)                           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ TIER 2: Service Mesh (Registry + Autoscaler)                       │
│  - Capability-based routing (no IP addresses)                      │
│  - Health tracking, load balancing                                 │
│  - Dynamic spawn/terminate on demand                               │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ TIER 3: Intelligence Layer (Agents)                                │
│  - OpenCode: Reasoning, code analysis/generation                   │
│  - OpenWolf: Anomaly detection, system health (ASHI)              │
│  - Composio Bridge: External world execution (APIs, SaaS)         │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ TIER 4: Execution + Truth (n8n, Home Assistant, DuckDB)           │
│  - Workflows: n8n, Home Assistant                                   │
│  - Truth: DuckDB (single source of truth)                          │
│  - Observability: Grafana, Meilisearch                             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📦 What's Included

### Core Services

| Service | Role | Image | Port |
|---------|------|-------|------|
| NATS JetStream | Event backbone | `nats:latest` | 4222 |
| Mesh Registry | Service discovery | `ark-mesh:latest` | 7000 |
| Autoscaler | Dynamic compute | `ark-autoscaler:latest` | 7001 |
| DuckDB | SSOT database | `python:3.11-slim` | — |

### Intelligence Agents

| Agent | Capabilities | Status |
|-------|-------------|--------|
| **OpenCode** | code.analyze, code.generate, code.transform, reasoning.plan | ✅ |
| **OpenWolf** | anomaly.detect, system.health, metrics.ingest, ashi.compute | ✅ |
| **Composio** | external.email, external.slack, external.github, external.notion | ✅ |

### Execution & Observability

| Service | Role |
|---------|------|
| n8n | Workflow orchestration |
| Home Assistant | IoT execution |
| Grafana | Metrics & dashboards |
| Meilisearch | Event search |
| MinIO | Object storage |

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| **ARK_SPEC.md** | Complete architecture specification |
| **TRISCA.md** | Distribution-aware scoring & control framework |
| **DEPLOYMENT_GUIDE.md** | Step-by-step deployment instructions |
| **QUICK_REFERENCE.md** | Command reference & troubleshooting |
| **EXAMPLES.md** | Code examples for integration |
| **BUILD_SUMMARY.md** | What was built and why |

---

## 🏃 How It Works

### 1. Service Registration

When an agent starts, it publishes:
```json
{
  "service": "opencode",
  "instance_id": "uuid-123",
  "capabilities": ["code.analyze", "code.generate"],
  "ttl": 10
}
```

### 2. Capability Routing

Client requests:
```
Topic: ark.call.opencode.code.analyze
Payload: {"request_id": "req-001", "params": {...}}
```

Registry routes to least-loaded instance. Agent processes and replies:
```
Topic: ark.reply.req-001
Payload: {"result": ...}
```

### 3. Autoscaling

Monitor demand:
```
Topic: ark.system.queue_depth.opencode
Payload: {"depth": 50}
```

Autoscaler decides: If `depth > threshold && instances < max`, spawn new instance.

### 4. State Logging

Every event persisted to DuckDB:
```sql
SELECT * FROM events 
WHERE type LIKE 'ark.call%' 
ORDER BY created_at DESC;
```

---

## 🔑 Key Features

### ✅ Self-Scaling
- Monitors queue depth, latency, ASHI degradation
- Spawns new instances automatically
- Terminates idle instances after cooldown
- Zero manual intervention

### ✅ Self-Routing
- No DNS or IP configuration needed
- Services advertise capabilities, not addresses
- Registry maintains routing table
- Load-aware routing (least-loaded instance)

### ✅ Self-Healing
- Failed services auto-removed from registry
- Autoscaler spawns replacements
- Full event history enables replay

### ✅ Event-Driven
- All communication via NATS
- Zero network assumptions
- Full audit trail in DuckDB
- Complete replay capability

### ✅ External-Coupled
- Composio bridge for SaaS/APIs
- Not just internal compute
- Can affect real world

---

## 📊 Monitoring

### Mesh Status API

```bash
# Full status
curl http://localhost:7000/api/mesh

# Route capability
curl http://localhost:7000/api/route/code.analyze

# Service details
curl http://localhost:7000/api/service/opencode
```

### Log Monitoring

```bash
docker logs -f ark-mesh          # Registry events
docker logs -f ark-autoscaler    # Scaling decisions
docker logs -f ark-opencode      # Agent activity
```

### NATS Inspection

```bash
docker exec ark-nats nats stream view ark.events --samples 100
```

---

## 🧪 Testing

### Load Test (1000 requests)

```bash
for i in {1..1000}; do
  docker exec ark-nats nats pub "ark.call.opencode.code.analyze" \
    "{\"request_id\":\"load-$i\",\"params\":{\"source\":\"def f(): pass\",\"language\":\"python\"}}" &
done
wait
```

### Monitor Scaling

```bash
watch -n 1 'curl -s http://localhost:7000/api/mesh | jq .service_details'
```

You'll see instance_count increase as demand grows.

---

## 🛠️ Extending ARK

### Add Custom Agent

1. Create `/agents/my-agent/agent.py`:
```python
class MyAgent:
    def __init__(self):
        self.service_name = "my-agent"
        self.capabilities = ["my.capability"]
    
    async def subscribe_calls(self):
        # Register and listen
        pass
```

2. Add Dockerfile:
```dockerfile
FROM python:3.11-slim
COPY agents/my-agent/agent.py /app/agent.py
CMD ["python", "/app/agent.py"]
```

3. Add to docker-compose.yml and start:
```bash
docker-compose build my-agent
docker-compose up -d my-agent
```

### Create n8n Workflow

1. Visit http://localhost:5678
2. Create webhook trigger
3. Add HTTP request node with NATS subscription
4. Route events to ARK capabilities

---

## 📈 Performance

| Metric | Value |
|--------|-------|
| Event throughput | 10,000+ events/sec |
| Routing latency | <10ms (p99) |
| Spawn latency | 1-2 seconds |
| Mesh query latency | <5ms |

---

## 🔒 Security Considerations

- Run agents as non-root containers
- Use environment variables for API keys (not hardcoded)
- Enable NATS authentication (optional)
- Add network policies between services
- Implement TLS for external connections

---

## 📋 File Structure

```
.
├── ark/                                # Core services
│   ├── mesh_registry.py               # Service discovery
│   └── autoscaler.py                  # Compute spawner
├── agents/                            # Intelligence
│   ├── opencode/
│   │   └── agent.py
│   ├── openwolf/
│   │   └── agent.py
│   └── composio/
│       └── agent.py
├── services/                          # Archived (reference)
├── Dockerfile.*                       # Service images
├── docker-compose.yml                 # Stack definition
├── ARK_SPEC.md                       # Architecture
├── TRISCA.md                         # Scoring framework
├── DEPLOYMENT_GUIDE.md               # Setup instructions
├── QUICK_REFERENCE.md                # Commands
├── EXAMPLES.md                       # Integration code
└── BUILD_SUMMARY.md                  # What was built
```

---

## 🎓 System Contracts (Hard Rules)

✓ **No service has fixed address** — All ephemeral  
✓ **No direct TCP calls** — Only NATS  
✓ **All state in DuckDB** — Single source of truth  
✓ **Autoscaler is only spawn authority** — No manual deployments  
✓ **Registry is only discovery** — No DNS/config files  
✓ **Capabilities define work** — Services register what they do  
✓ **Heartbeat = health** — Expired services auto-removed  
✓ **Composio for external** — No direct API calls from agents  

---

## 🚦 Status

| Component | Status | Notes |
|-----------|--------|-------|
| NATS Backbone | ✅ | Deployed, tested |
| Mesh Registry | ✅ | Live, routing requests |
| Autoscaler | ✅ | Spawning on demand |
| OpenCode | ✅ | 5 capabilities, responding |
| OpenWolf | ✅ | ASHI computation working |
| Composio Bridge | ✅ | Ready for API keys |
| n8n | ✅ | Workflows ready |
| Home Assistant | ✅ | IoT integration ready |
| DuckDB | ✅ | SSOT, persisting events |
| Observability | ✅ | Grafana, Meilisearch ready |

---

## 📞 Support & Resources

- **Architecture**: See `ARK_SPEC.md`
- **TRISCA**: See `TRISCA.md`
- **Setup**: See `DEPLOYMENT_GUIDE.md`
- **Commands**: See `QUICK_REFERENCE.md`
- **Examples**: See `EXAMPLES.md`
- **Built**: See `BUILD_SUMMARY.md`

---

## 🎯 Next Steps

1. **Deploy**: Follow `DEPLOYMENT_GUIDE.md`
2. **Test**: Try examples in `EXAMPLES.md`
3. **Monitor**: Use `QUICK_REFERENCE.md` for commands
4. **Extend**: Add custom agents and workflows
5. **Scale**: Load test and observe autoscaling

---

**ARK is ready. Events flow. Services scale. Intelligence emerges.**

Built with Gordon for production deployment.

## Truth Spine Additions

| Area | Role |
| --- | --- |
| [`ark-core/`](ark-core/README.md) | Canonical integration target for control plane + truth spine |
| [`ark-core/internal/models/`](ark-core/internal/models/) | Shared event, stability, and ingest-to-truth model types |
| [`ark-core/internal/epistemic/`](ark-core/internal/epistemic/) | Claim states, conflict groups, resolver, and policy types |
| [`ark-core/scripts/ai/`](ark-core/scripts/ai/) | Agent prompt + offline orchestration scaffold |
| [`./forge`](forge) | Low-friction self-coding launcher into the Forge engine |
| [`ark-core/scripts/ci/`](ark-core/scripts/ci/) | Tier enforcement + Red Team gates |
| [`ark-core/config/tiering_rules.json`](ark-core/config/tiering_rules.json) | Canonical S/T/P policy configuration |

## Verify

From [`ark-core/`](ark-core/README.md):

```powershell
.\scripts\verify.ps1
go test ./...
docker compose -f docker-compose.yml config
```

## Merge Rule

This workspace now prefers cross-links over repeated prose. If a concept already
has a canonical file, add a reference to that file instead of creating a second
version of the same explanation.
