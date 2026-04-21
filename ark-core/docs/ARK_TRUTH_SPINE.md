# ARK Truth Spine

`ARK_TRUTH_SPINE.md` is the canonical long-form architecture source for ARK's
ingest-to-truth system. Other docs should link here instead of restating this
material.

## 1. Universal ingest-to-truth summary

Full system = one universal ingest-to-truth architecture:

```text
Anything external
-> ingest once
-> store raw once
-> extract atomic facts
-> link into reference graph
-> resolve into SSOT
-> derive fields/views/events
-> query/map/simulate in ARK
```

Built for:

- any dataset
- any media
- minimal redundancy
- maximum metadata
- orthogonal design
- traceable truth

## 2. Top-level system and core planes

Core planes:

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

Compressed:

```text
Source world
-> EDI
-> Raw Archive
-> Reference Graph
-> Resolver
-> SSOT
-> Field Engine
-> API / UI / ARK consumers
```

## 3. Core design laws

The 8 laws:

1. Store once
2. Derive many
3. Project late
4. Cache only when hot
5. Graph can disagree
6. SSOT cannot disagree with itself
7. Every fact must trace to raw
8. Every axis stays orthogonal

## 4. Orthogonal axes

Everything is separated into independent dimensions:

1. Source
2. Entity
3. Time
4. Geo
5. Category / Taxonomy
6. Metric
7. Policy
8. Uncertainty
9. Version

Formal:

```text
Source ⟂ Entity ⟂ Time ⟂ Geo ⟂ Category ⟂ Metric ⟂ Policy
```

This means:

- changing taxonomy does not change raw
- changing geo mapping does not mutate source facts
- changing policy does not rewrite history
- changing metric formulas does not duplicate data

## 5. Storage classes

### A. Raw immutable store

Holds:

- original files
- pages
- feeds
- media
- snapshots

Stored as:

- compressed blobs
- content-addressed
- one canonical copy

Purpose:

- audit
- replay
- reparse

### B. Structural index

Holds:

- byte spans
- timestamps
- frame ranges
- scene boundaries
- pages
- sections
- paragraph offsets

Purpose:

- point into raw without copying content

### C. Semantic layer

Holds:

- atomic facts
- claims
- entity mentions
- category assignments
- relationships
- provenance edges
- confidence
- uncertainty

Purpose:

- maximum metadata density

### D. Reference graph

Holds:

- canonical entities
- aliases
- claims
- source links
- inter-entity relationships
- conflicting truths

Purpose:

- semantic memory

### E. SSOT

Holds:

- current accepted value per governed key
- policy version
- lineage pointers

Purpose:

- operational truth

### F. Accelerators

Holds:

- hot materialized views
- tiles
- top lists
- dashboards
- cached search results

Purpose:

- speed only

Delete and rebuild anytime.

## 6. Main services

### 1. SCRIBE / EDI

Does:

- fetch
- poll
- sync
- snapshot
- parse
- normalize
- attach provenance
- emit ingest events

Does not:

- declare truth
- write directly into SSOT

### 2. ARCHIVE

Does:

- immutable blob storage
- CID/hash-based addressing
- compression
- retention
- replay source

### 3. EXTRACTOR layer

Does:

- entity extraction
- claim extraction
- subtitle/transcript parsing
- scene detection
- OCR
- audio segmentation
- taxonomy tagging
- geo hints
- time hints

### 4. REFERENCE GRAPH service

Does:

- entity creation
- alias linking
- fact storage
- provenance edges
- conflict preservation
- graph traversal

### 5. RESOLVER / POLICY ENGINE

Does:

- decide what claim wins
- resolve conflicts
- choose current canonical state
- score trust
- apply policy version

Output:

- SSOT projection candidates

### 6. SSOT projector

Does:

- maintain current clean state
- guarantee one answer per governed key
- keep lineage to source claims

### 7. FIELD ENGINE

Does:

- aggregation
- normalization
- residuals
- entropy
- gini
- trend
- uncertainty
- TRISCA/composite scores

Produces:

- geo/time fields
- topic/time fields
- entity/time fields

### 8. GUARD

Does:

- enforce invariants
- block bad projections
- damp unstable updates
- quarantine low-confidence jumps

### 9. REAPER

Does:

- isolate bad sources
- quarantine poisoned streams
- sink unstable artifacts

### 10. FORGE

Does:

- reparse
- relink
- recompute
- rebuild projections when models improve

### 11. ATLAS

Does:

- routing
- querying
- graph + geo + time projection
- multi-domain joins

### 12. Event bus

Does:

- append-only system events
- replay
- fanout
- downstream processing

Design flavor:

- JetStream / NATS style authoritative log

## 7. Data object model

### Raw artifact

One upstream object.

Fields:

- artifact_id
- source_type
- source_url
- fetched_at
- cid/hash
- compression
- size
- blob_ref

### Span

A pointer into raw.

Fields:

- span_id
- artifact_id
- start/end byte
- t_start/t_end
- frame_start/frame_end
- page/section/paragraph markers

### Entity

Canonical thing.

Fields:

- entity_id
- entity_type
- aliases
- canonical label
- confidence

### Claim / atomic fact

Unit of meaning.

Fields:

- fact_id
- subject
- predicate
- object / value
- span_id
- valid_time
- confidence

### Provenance edge

Why a fact exists.

Fields:

- fact_id
- artifact_id
- extraction method
- parser/model version
- support weight

### SSOT record

Current accepted truth.

Fields:

- ssot_key
- current_value/state
- policy_version
- derived_from facts
- updated_at

### Metric / field record

Derived signal.

Fields:

- domain
- geo/topic/entity
- t
- total
- rate
- residual
- entropy
- gini
- velocity
- uncertainty
- composite score

## 8. Epistemic pipeline and truth model

All knowledge must pass through an explicit staged pipeline:

```text
raw -> observed -> extracted -> linked -> contested -> resolved -> accepted
```

Public truth layers:

1. observed
2. referenced / linked
3. accepted

Internal claim lifecycle:

1. observed
2. extracted
3. linked
4. contested
5. resolved
6. accepted
7. rejected

Hard boundary:

```text
claims != truth
only SSOT is actionable truth
no component may treat a claim as truth unless it came from SSOT
```

Resolver flow:

```text
claims -> resolver -> candidates -> policy -> accepted SSOT
```

## 9. Conflict system

Conflict is preserved in the graph and prohibited inside SSOT:

```text
graph may contain contradictions
SSOT may not
```

Rule:

```text
same subject + predicate + same/overlapping time + different values
=> conflict group
```

Conflict/support signals:

- conflict_size
- variance_score
- source_diversity
- agreement_ratio
- conflict_entropy
- support_strength
- conflict_pressure
- uncertainty_breakdown
- narrative_clusters

Three simultaneous views:

1. observed truth = what was said
2. contested truth = what disagrees
3. operational truth = what the system acts on

## 10. Universal adapter contract

Any dataset plugs in through a thin adapter:

1. `entity_key(raw)`
2. `measures(raw)`
3. `denominator(context)`
4. `controls(context)`
5. `categories(raw)`
6. `geo_resolve(raw)`
7. `time_resolve(raw)`
8. `uncertainty(row)`

This lets one system handle:

- federal case data
- wages
- retail closures
- news
- Wikipedia
- movies
- music
- images
- sensor data
- network data

## 11. Universal math layer

Core formulas:

Normalize:

```text
rate = total / denominator
```

Control:

```text
residual = Z(rate) - Z(control_proxy)
```

Structure:

```text
entropy = -Σ p_i log p_i
gini = inequality(p_i)
```

Dynamics:

```text
velocity = x_t - x_t-1
```

Uncertainty:

```text
U = f(missing, noise, geo_conf, source_mix, conflict)
```

Composite:

```text
score = weighted(residual, rate, entropy, gini, velocity, -uncertainty)
```

All math-layer outputs are derived values, never raw truth.

## 12. Database stack

Minimal canonical stack:

1. Postgres = core brain/storage
2. PostGIS = maps/location
3. TimescaleDB = time/history
4. pgvector = similarity/pattern matching

Optional:

5. graph extension or plain relational graph tables
6. object storage for raw blobs
7. event bus for replay

Compressed:

```text
Postgres = brain
PostGIS = eyes
Timescale = memory
pgvector = intuition
```

## 13. Minimum-redundancy rules

Hard rules:

1. raw payload stored once
2. semantic meaning stored as atomic facts
3. entities stored once, aliases linked
4. source text never copied into every layer
5. derived metrics stored only if hot
6. embeddings stored once per stable segment/model version
7. no service-local truth copies
8. all caches disposable

## 14. Maximum-metadata strategy

To maximize metadata per byte:

1. use span-linked facts
2. use IDs instead of repeated strings
3. use delta versioning
4. use pointer-heavy design
5. use sparse graph edges
6. keep SSOT thin
7. put blobs in object storage
8. keep relational core narrow and precise

Ideal pattern:

```text
blob once
+ spans
+ facts
+ edges
+ thin truth projection
```

## 15. Media support

Any media becomes an artifact.

Text:

- paragraphs
- entities
- claims
- citations

News:

- stories
- outlets
- frames
- locations
- time trends

Wikipedia:

- page revisions
- edit velocity
- conflict
- citation density
- narrative drift

Movies/video:

- scenes
- shots
- transcript
- visual objects
- audio motifs
- embeddings

Music/audio:

- segments
- tempo
- energy
- lyrics
- motifs
- themes

Images:

- objects
- OCR
- logos
- places
- visual embeddings

All media ends up as:

- artifact
- spans/slices
- facts
- graph links
- optional SSOT facts

## 16. Invariants

Non-negotiables:

1. raw never disappears
2. every accepted fact has lineage
3. graph may contain contradictions
4. SSOT may not
5. no rate without denominator
6. no geo without confidence
7. no category without scheme version
8. no policy-free SSOT update
9. all updates append, not silent overwrite
10. uncertainty always travels with inference

## 17. Typical pipelines

Example: external article

```text
article
-> snapshot
-> blob store
-> paragraph spans
-> entity/claim extraction
-> graph nodes/edges
-> resolve canonical entities
-> SSOT if policy permits
-> field metrics / events
```

Example: movie

```text
video
-> hash + metadata
-> scene segmentation
-> audio/text/visual extraction
-> time-indexed facts
-> graph
-> joins with outside data
```

Example: Wikipedia

```text
page dump/revision
-> revision chain
-> claim drift
-> source/citation graph
-> conflict scoring
-> your own trusted projection
```

## 18. Query modes

The same spine should answer:

Fact queries:

- what is the current accepted value?

Lineage queries:

- where did this come from?

Conflict queries:

- what sources disagree?

Field queries:

- where is this rising/falling?

Graph queries:

- what is connected to this?

Similarity queries:

- what looks like this?

Drift queries:

- how has this changed over time?

Cross-domain joins:

- how do media, news, cases, and geography interact?

## 19. Output types

SSOT outputs:

- canonical records
- current states

Graph outputs:

- entities
- claims
- source relations
- conflict neighborhoods

Field outputs:

- maps
- time series
- rankings
- residual clusters
- TRISCA-like composites

Event outputs:

- signed replayable deltas
- alerts
- downstream triggers

## 20. Minimal deployment version

The smallest real version:

1. Postgres
2. PostGIS
3. TimescaleDB
4. pgvector
5. object storage for blobs
6. one ingest service
7. one graph/SSOT schema
8. one event stream
9. one API

That is enough to start.

## 21. Next-phase backlog

The current repo pass is additive scaffolding. Later phases should wire:

- the epistemic pipeline into Postgres schema + ingest
- full truth-spine services/schema
- end-to-end signed envelopes everywhere
- real mTLS
- full policy proofs
- all runtime endpoints across services
- event topics and service boundaries
- the first working ingest -> SSOT pipeline

Documented future API surfaces:

- `GET /conflicts/:entity`
- `GET /conflicts/:group_id`
- `GET /ssot/:key?include_conflicts=true`

Documented future Red Team scenario stubs:

- `internal/redteam/scenarios/conflict_injection.go`
- `internal/redteam/scenarios/false_consensus.go`
- `internal/redteam/scenarios/adversarial_source.go`

## 22. Final system compression

ARK full data system = a universal, orthogonal, low-redundancy,
provenance-preserving ingest-to-truth engine that can turn any raw source or
media into traceable facts, graph structure, field metrics, and operational
SSOT state.
