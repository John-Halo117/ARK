package models

import "time"

// CIDObject is the immutable CAS envelope stored on the NAS and replicated
// through the mesh. Readers must verify the CID before trusting the payload.
type CIDObject struct {
	CID          string            `json:"cid"`
	HashAlg      string            `json:"hash_alg"`
	Codec        string            `json:"codec"`
	Sequence     uint64            `json:"sequence"`
	StateHash    string            `json:"state_hash"`
	CanonicalRef string            `json:"canonical_ref"`
	CASPath      string            `json:"cas_path"`
	SizeBytes    int64             `json:"size_bytes"`
	Compression  string            `json:"compression"`
	Verified     bool              `json:"verified"`
	CreatedAt    time.Time         `json:"created_at"`
	Metadata     map[string]string `json:"metadata,omitempty"`
}
