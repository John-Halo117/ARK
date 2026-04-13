# ARK OS - Complete Documentation Index

Welcome to ARK: A self-scaling, event-driven intelligent operating system.

---

## 🚀 Start Here

**New to ARK?** Start with these in order:

1. **README.md** - System overview, quick start, feature summary
2. **QUICK_REFERENCE.md** - Essential commands for daily use
3. **DEPLOYMENT_GUIDE.md** - Step-by-step setup instructions

---

## 📚 Core Architecture

| Document | Purpose | Read Time |
|----------|---------|-----------|
| **ARK_SPEC.md** | Complete system architecture & design | 20 min |
| **SYSTEM_MAP.md** | Visual architecture, service inventory, data flows | 15 min |
| **BUILD_SUMMARY.md** | What was built and why | 10 min |

---

## 🔌 Emitters (Data Sources)

These documents cover Home Assistant, Jellyfin, and UniFi integration:

| Document | Purpose | Read Time |
|----------|---------|-----------|
| **EMITTERS_GUIDE.md** | Configuration, capabilities, troubleshooting | 25 min |
| **EMITTER_WORKFLOWS.md** | Real-world automation patterns & examples | 20 min |
| **EMITTERS_QUICK_REF.md** | Quick command reference for emitters | 5 min |
| **EMITTERS_SUMMARY.md** | Integration overview & summary | 10 min |
| **EMITTERS_DELIVERY.md** | What was delivered, checklist | 15 min |

---

## 💻 Integration & Development

| Document | Purpose | Read Time |
|----------|---------|-----------|
| **EXAMPLES.md** | Code examples: Python, n8n, Home Assistant | 20 min |
| **INTEGRATION_GUIDE.md** | Event publishing, DuckDB queries, agent creation | 15 min |

---

## 🎯 Quick Navigation

### I want to...

**Deploy ARK**
→ Read: DEPLOYMENT_GUIDE.md

**Understand the architecture**
→ Read: ARK_SPEC.md or SYSTEM_MAP.md

**Set up emitters (Home Assistant, Jellyfin, UniFi)**
→ Read: EMITTERS_GUIDE.md

**Create automations with emitter events**
→ Read: EMITTER_WORKFLOWS.md

**Write custom agents**
→ Read: EXAMPLES.md (agent template section)

**Debug issues**
→ Read: QUICK_REFERENCE.md (troubleshooting) or EMITTERS_GUIDE.md (emitter issues)

**Understand event flows**
→ Read: SYSTEM_MAP.md (complete flows)

**Learn about capabilities**
→ Read: EMITTERS_GUIDE.md (capabilities section)

**Monitor production system**
→ Read: QUICK_REFERENCE.md (monitoring section)

---

## 📋 Complete File Listing

### Core System Files

```
Core Services:
  ark/
    ├── mesh_registry.py          Service discovery (1,239 lines)
    └── autoscaler.py             Dynamic compute spawning (1,091 lines)

Agents:
  agents/
    ├── opencode/agent.py         Reasoning agent (890 lines)
    ├── openwolf/agent.py         Health agent (1,162 lines)
    └── composio/agent.py         External execution (970 lines)

Emitters:
  emitters/
    ├── homeassistant_emitter.py  HA state monitoring (527 lines)
    ├── jellyfin_emitter.py       Media event tracking (564 lines)
    └── unifi_emitter.py          Network monitoring (564 lines)
```

### Docker Configuration

```
Dockerfiles:
  Dockerfile.mesh                 Mesh registry image
  Dockerfile.autoscaler           Autoscaler image
  Dockerfile.opencode             OpenCode agent image
  Dockerfile.openwolf             OpenWolf agent image
  Dockerfile.composio             Composio bridge image
  Dockerfile.ha-emitter           HA emitter image
  Dockerfile.jellyfin-emitter     Jellyfin emitter image
  Dockerfile.unifi-emitter        UniFi emitter image

Orchestration:
  docker-compose.yml              Complete stack definition (15 services)
```

### Documentation (by category)

```
Getting Started:
  README.md                       System overview & quick start
  QUICK_REFERENCE.md              Essential commands (8.5 KB)
  DEPLOYMENT_GUIDE.md             Step-by-step setup (6.2 KB)

Architecture:
  ARK_SPEC.md                     Complete specification (9.9 KB)
  SYSTEM_MAP.md                   Architecture & data flows (15.0 KB)
  BUILD_SUMMARY.md                What was built (9.2 KB)

Emitters:
  EMITTERS_GUIDE.md               Configuration guide (11.1 KB)
  EMITTER_WORKFLOWS.md            Automation patterns (11.1 KB)
  EMITTERS_QUICK_REF.md           Command reference (8.5 KB)
  EMITTERS_SUMMARY.md             Integration overview (11.2 KB)
  EMITTERS_DELIVERY.md            Delivery summary (11.3 KB)

Integration:
  EXAMPLES.md                     Code examples (11.5 KB)
  INTEGRATION_GUIDE.md            Event publishing & queries (5.1 KB)
```

### Configuration

```
.gitignore                        Standard ignores
```

---

## 🎓 Learning Paths

### Path 1: Get Running (30 minutes)
1. README.md (5 min)
2. DEPLOYMENT_GUIDE.md (15 min)
3. QUICK_REFERENCE.md (10 min)
4. Deploy and test

### Path 2: Understand Architecture (1 hour)
1. ARK_SPEC.md (20 min)
2. SYSTEM_MAP.md (15 min)
3. BUILD_SUMMARY.md (10 min)
4. Diagram on paper (15 min)

### Path 3: Set Up Emitters (45 minutes)
1. EMITTERS_GUIDE.md - Configuration section (10 min)
2. EMITTERS_QUICK_REF.md - Setup commands (5 min)
3. Deploy emitters (15 min)
4. Verify events flowing (5 min)
5. EMITTERS_SUMMARY.md (10 min)

### Path 4: Create Automations (2 hours)
1. EMITTER_WORKFLOWS.md (20 min)
2. EXAMPLES.md - n8n workflow section (15 min)
3. Create workflow in n8n (60 min)
4. Test and refine (25 min)

### Path 5: Develop Custom Agents (3 hours)
1. EXAMPLES.md - Agent template (15 min)
2. EXAMPLES.md - Custom agent example (15 min)
3. ARK_SPEC.md - Agent contract section (10 min)
4. Write and test agent (120 min)

---

## 🔧 Common Tasks

### Deploy ARK
See: DEPLOYMENT_GUIDE.md

### Configure Home Assistant
See: EMITTERS_GUIDE.md → Home Assistant Emitter section

### Configure Jellyfin
See: EMITTERS_GUIDE.md → Jellyfin Emitter section

### Configure UniFi
See: EMITTERS_GUIDE.md → UniFi Emitter section

### Create n8n Workflow
See: EMITTER_WORKFLOWS.md or EXAMPLES.md

### Write Custom Agent
See: EXAMPLES.md → Custom Agent Template

### Query DuckDB
See: EXAMPLES.md → DuckDB Queries section

### Debug Issues
See: QUICK_REFERENCE.md → Troubleshooting or
     EMITTERS_GUIDE.md → Troubleshooting section

### Monitor System
See: QUICK_REFERENCE.md → Monitor Logs section

### Check Event Flow
See: QUICK_REFERENCE.md → Test Capability Routing

---

## 📊 Documentation Statistics

- **Total documentation**: 120+ KB
- **Code examples**: 50+
- **Architecture diagrams**: 3
- **Configuration examples**: 40+
- **Troubleshooting scenarios**: 20+
- **Integration patterns**: 7

---

## 🚦 System Status

### Components Implemented

✅ NATS JetStream (event backbone)  
✅ Mesh Registry (service discovery)  
✅ Autoscaler (dynamic compute)  
✅ DuckDB (SSOT)  
✅ OpenCode Agent (reasoning)  
✅ OpenWolf Agent (health)  
✅ Composio Bridge (external execution)  
✅ Home Assistant Emitter  
✅ Jellyfin Emitter  
✅ UniFi Emitter  
✅ n8n (workflow engine)  
✅ Grafana (observability)  
✅ Meilisearch (search)  

### Documentation Complete

✅ Architecture specification  
✅ Deployment guide  
✅ Configuration guides  
✅ Integration examples  
✅ Workflow patterns  
✅ API documentation  
✅ Troubleshooting guides  
✅ Quick references  

---

## 🔗 Cross-References

**From core ARK_SPEC.md:**
→ See SYSTEM_MAP.md for data flows
→ See DEPLOYMENT_GUIDE.md for setup
→ See QUICK_REFERENCE.md for commands

**From EMITTERS_GUIDE.md:**
→ See EMITTER_WORKFLOWS.md for patterns
→ See EXAMPLES.md for code samples
→ See QUICK_REFERENCE.md for commands

**From EXAMPLES.md:**
→ See INTEGRATION_GUIDE.md for more examples
→ See EMITTERS_GUIDE.md for emitter details
→ See ARK_SPEC.md for architecture context

---

## 📱 Mobile/Quick Access

**For phone/quick reference:**
- QUICK_REFERENCE.md - All essential commands
- EMITTERS_QUICK_REF.md - Emitter commands only

**For offline reading:**
- Download README.md + ARK_SPEC.md + DEPLOYMENT_GUIDE.md

**For presentations:**
- Use SYSTEM_MAP.md diagrams
- Show BUILD_SUMMARY.md for scope

---

## 🎯 What ARK Does (TL;DR)

```
Your infrastructure (HA, Jellyfin, UniFi)
         ↓
Three emitters collect events
         ↓
NATS distributes events
         ↓
Agents process intelligently
         ↓
Workflows execute automations
         ↓
DuckDB stores everything
         ↓
System learns patterns
```

---

## 📞 For Help

**Setup issues?** → DEPLOYMENT_GUIDE.md + QUICK_REFERENCE.md troubleshooting

**Emitter problems?** → EMITTERS_GUIDE.md troubleshooting + EMITTERS_QUICK_REF.md

**Architecture questions?** → ARK_SPEC.md + SYSTEM_MAP.md

**Integration help?** → EXAMPLES.md + EMITTER_WORKFLOWS.md

**Code examples?** → EXAMPLES.md (50+ examples)

---

## ✨ Key Documents by Purpose

| Purpose | Primary Doc | Secondary Doc |
|---------|------------|---------------|
| Deploy system | DEPLOYMENT_GUIDE.md | QUICK_REFERENCE.md |
| Understand design | ARK_SPEC.md | SYSTEM_MAP.md |
| Set up data sources | EMITTERS_GUIDE.md | EMITTERS_QUICK_REF.md |
| Create automations | EMITTER_WORKFLOWS.md | EXAMPLES.md |
| Write agents | EXAMPLES.md | ARK_SPEC.md |
| Query data | EXAMPLES.md | INTEGRATION_GUIDE.md |
| Debug | QUICK_REFERENCE.md | EMITTERS_GUIDE.md |
| Monitor | SYSTEM_MAP.md | QUICK_REFERENCE.md |

---

## 🏁 You Are Ready

You have:
- ✅ Complete source code
- ✅ Docker configuration
- ✅ Complete documentation
- ✅ Integration examples
- ✅ Troubleshooting guides
- ✅ Quick references

**Start with README.md and DEPLOYMENT_GUIDE.md**

**Then customize with EMITTERS_GUIDE.md and EMITTER_WORKFLOWS.md**

**Build with EXAMPLES.md**

---

**Welcome to ARK. Your infrastructure is now intelligent.**
