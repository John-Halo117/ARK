// Package subjects is the single source of truth for NATS subject and stream
// names used by Go services in ARK-Field. Keep in sync with ark/subjects.py
// and GLOSSARY.md §1.2 — never hard-code subject strings elsewhere.
package subjects

// Ingestion / CID event backbone.
const (
	// EventsCID carries canonical CID events produced by the single-writer
	// ingestion leader.
	EventsCID = "ark.events.cid"

	// EventsStream is the JetStream name that persists EventsCID messages.
	EventsStream = "ARK_EVENTS"
)
