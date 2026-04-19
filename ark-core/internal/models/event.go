package models

import "time"

// Event is the canonical normalized unit emitted by the Ingestion Leader.
// Every mutation is derived from a Git commit before it becomes an event.
type Event struct {
	CID        string            `json:"cid"`
	Sequence   uint64            `json:"sequence"`
	Type       string            `json:"type"`
	StateHash  string            `json:"state_hash"`
	GitCommit  string            `json:"git_commit"`
	GitRepo    string            `json:"git_repo"`
	ParentCID  string            `json:"parent_cid,omitempty"`
	Author     string            `json:"author,omitempty"`
	OccurredAt time.Time         `json:"occurred_at"`
	Transport  string            `json:"transport"`
	PayloadRef string            `json:"payload_ref,omitempty"`
	Metadata   map[string]string `json:"metadata,omitempty"`
}
