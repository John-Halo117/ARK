# ARK System Map

`SYSTEM_MAP.md` is the compressed topology view. For the full architecture, see
[`ARK_TRUTH_SPINE.md`](ARK_TRUTH_SPINE.md).

## Core planes

1. External Data Ingest (EDI / SCRIBE)
2. Immutable Raw Archive
3. Reference Graph
4. Resolver / Policy Engine
5. SSOT Projection
6. Field / Metric Engine
7. Event Bus
8. Serving / Query Layer
9. Cache / Materialization Layer
10. GUARD / REAPER / FORGE controls

## Compressed flow

```text
WORLD
-> SCRIBE / EDI
-> ARCHIVE
-> SPANS + ATOMIC FACTS
-> REFERENCE GRAPH
-> RESOLVER / POLICY
-> SSOT
-> FIELD ENGINE
-> ATLAS / API / MAPS / QUERIES / EVENTS
-> GUARD / REAPER / FORGE
```

## Control roles

Control plane:

- NetWatch
- CI
- Recovery

Truth spine:

- Ingest
- Archive
- Extract
- Graph
- Resolver
- SSOT
- Field Engine
- ATLAS

Enforcement:

- Policy
- Tiers
- Red Team
- Proof/Audit
- Event Bus

Stability:

- GUARD enforces invariants and dampens unstable projections
- REAPER isolates poisoned or unstable sources
- FORGE reparses, relinks, and rebuilds as models improve
