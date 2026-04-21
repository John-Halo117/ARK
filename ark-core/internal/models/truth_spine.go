package models

import (
	"time"

	"github.com/John-Halo117/ARK/ark-core/internal/epistemic"
)

// Artifact is the immutable raw object captured from an external source.
type Artifact struct {
	ArtifactID  string    `json:"artifact_id"`
	SourceType  string    `json:"source_type"`
	SourceURL   string    `json:"source_url,omitempty"`
	FetchedAt   time.Time `json:"fetched_at"`
	CID         string    `json:"cid,omitempty"`
	Hash        string    `json:"hash,omitempty"`
	Compression string    `json:"compression,omitempty"`
	SizeBytes   int64     `json:"size_bytes,omitempty"`
	BlobRef     string    `json:"blob_ref,omitempty"`
}

// Span points into raw storage without duplicating source content.
type Span struct {
	SpanID          string  `json:"span_id"`
	ArtifactID      string  `json:"artifact_id"`
	StartByte       int64   `json:"start_byte,omitempty"`
	EndByte         int64   `json:"end_byte,omitempty"`
	StartSeconds    float64 `json:"t_start,omitempty"`
	EndSeconds      float64 `json:"t_end,omitempty"`
	FrameStart      int64   `json:"frame_start,omitempty"`
	FrameEnd        int64   `json:"frame_end,omitempty"`
	PageMarker      string  `json:"page_marker,omitempty"`
	SectionMarker   string  `json:"section_marker,omitempty"`
	ParagraphMarker string  `json:"paragraph_marker,omitempty"`
}

// Entity is the canonical, alias-aware node used by the reference graph.
type Entity struct {
	EntityID       string   `json:"entity_id"`
	EntityType     string   `json:"entity_type"`
	Aliases        []string `json:"aliases,omitempty"`
	CanonicalLabel string   `json:"canonical_label"`
	Confidence     float64  `json:"confidence"`
}

// Claim is the atomic semantic unit extracted from raw input.
type Claim struct {
	FactID          string                `json:"fact_id"`
	Subject         string                `json:"subject"`
	Predicate       string                `json:"predicate"`
	ObjectValue     any                   `json:"object_value"`
	SpanID          string                `json:"span_id,omitempty"`
	ValidTime       *time.Time            `json:"valid_time,omitempty"`
	Confidence      float64               `json:"confidence"`
	State           epistemic.ClaimState  `json:"state"`
	ConflictGroupID string                `json:"conflict_group_id,omitempty"`
	PolicyVersion   string                `json:"policy_version,omitempty"`
}

// ProvenanceEdge explains why a claim exists and how it was produced.
type ProvenanceEdge struct {
	FactID           string  `json:"fact_id"`
	ArtifactID       string  `json:"artifact_id"`
	ExtractionMethod string  `json:"extraction_method"`
	ParserVersion    string  `json:"parser_version,omitempty"`
	SupportWeight    float64 `json:"support_weight"`
}

// SSOTRecord is the operational truth projection selected by policy.
type SSOTRecord struct {
	SSOTKey          string    `json:"ssot_key"`
	CurrentValue     any       `json:"current_value,omitempty"`
	CurrentState     string    `json:"current_state,omitempty"`
	PolicyVersion    string    `json:"policy_version"`
	DerivedFrom      []string  `json:"derived_from,omitempty"`
	ConflictGroupID  string    `json:"conflict_group_id,omitempty"`
	Confidence       float64   `json:"confidence,omitempty"`
	Uncertainty      float64   `json:"uncertainty,omitempty"`
	SupportStrength  float64   `json:"support_strength,omitempty"`
	ConflictPressure float64   `json:"conflict_pressure,omitempty"`
	UpdatedAt        time.Time `json:"updated_at"`
}

// MetricRecord holds derived-only field-engine output keyed by a domain slice.
type MetricRecord struct {
	Domain         string    `json:"domain"`
	SubjectKey     string    `json:"subject_key"`
	Timestamp      time.Time `json:"timestamp"`
	Total          float64   `json:"total,omitempty"`
	Denominator    float64   `json:"denominator,omitempty"`
	Rate           float64   `json:"rate,omitempty"`
	Residual       float64   `json:"residual,omitempty"`
	Entropy        float64   `json:"entropy,omitempty"`
	Gini           float64   `json:"gini,omitempty"`
	Velocity       float64   `json:"velocity,omitempty"`
	Uncertainty    float64   `json:"uncertainty,omitempty"`
	CompositeScore float64   `json:"composite_score,omitempty"`
}
