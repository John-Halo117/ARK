package midas

import (
	"context"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/shared"
)

const (
	DefaultRuntimeCap   = 100 * time.Millisecond
	DefaultMemoryCapMiB = 16
	DefaultMaxBlobBytes = 2 * 1024 * 1024
	DefaultMaxMatches   = 8
)

type BlobReader interface {
	ReadCanonical(ctx context.Context, path string, maxBytes int) ([]byte, error)
}

type Embedder interface {
	Embed(ctx context.Context, blob []byte) ([]float64, error)
}

type Index interface {
	Search(ctx context.Context, embedding []float64, limit int) ([]shared.Match, error)
}

type Extractor interface {
	Extract(ctx context.Context, input ExtractInput) ([]shared.Primitive, error)
}

type SidecarWriter interface {
	WriteSidecar(ctx context.Context, sidecar shared.Sidecar) error
}

type ExtractInput struct {
	Hash      string         `json:"hash"`
	Path      string         `json:"path"`
	Blob      []byte         `json:"blob"`
	Embedding []float64      `json:"embedding"`
	Matches   []shared.Match `json:"matches"`
}

type Config struct {
	MaxBlobBytes int
	MaxMatches   int
	RuntimeCap   time.Duration
	MemoryCapMiB int
}

type Dependencies struct {
	Reader    BlobReader
	Embedder  Embedder
	Index     Index
	Extractor Extractor
	Writer    SidecarWriter
}

type MIDASCore struct {
	deps Dependencies
	cfg  Config
}

func New(deps Dependencies, cfg Config) (MIDASCore, error) {
	normalized := normalizeConfig(cfg)
	if err := validateDependencies(deps); err != nil {
		return MIDASCore{}, err
	}
	if err := validateConfig(normalized); err != nil {
		return MIDASCore{}, err
	}
	return MIDASCore{deps: deps, cfg: normalized}, nil
}

func (m MIDASCore) Health() shared.HealthStatus {
	cfg := normalizeConfig(m.cfg)
	return shared.HealthStatus{Status: "ok", Module: "internal.midas", RuntimeCap: cfg.RuntimeCap, MemoryCapMiB: cfg.MemoryCapMiB}
}

// Enrich input schema: context.Context, canonical hash, canonical path.
// Output schema: shared.Sidecar or shared.Failure error.
// Runtime constraint: O(blob bytes + embedding dims + primitive count), capped by Config.
// Memory assumption: O(blob bytes + embedding dims + primitive count), capped by Config and shared bounds.
// Failure cases: missing dependencies, invalid path/hash, read/embed/index/extract/write failure, oversized outputs, canceled context.
// Determinism: same dependencies and canonical blob produce the same sidecar.
func (m MIDASCore) Enrich(ctx context.Context, hash string, path string) (shared.Sidecar, error) {
	cfg := normalizeConfig(m.cfg)
	if ctx == nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_CONTEXT_REQUIRED", "context is required", nil, false)
	}
	if err := validateDependencies(m.deps); err != nil {
		return shared.Sidecar{}, err
	}
	if err := validateConfig(cfg); err != nil {
		return shared.Sidecar{}, err
	}
	if err := shared.ValidateHash(hash); err != nil {
		return shared.Sidecar{}, err
	}
	if err := shared.ValidatePath(path); err != nil {
		return shared.Sidecar{}, err
	}
	if err := ctx.Err(); err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_CONTEXT_CANCELED", err.Error(), nil, true)
	}

	blob, err := m.deps.Reader.ReadCanonical(ctx, path, cfg.MaxBlobBytes)
	if err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_READ_FAILED", err.Error(), map[string]any{"path": path}, true)
	}
	if len(blob) > cfg.MaxBlobBytes {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_BLOB_TOO_LARGE", "canonical blob exceeds configured bound", map[string]any{"max_bytes": cfg.MaxBlobBytes}, false)
	}
	if err := ctx.Err(); err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_CONTEXT_CANCELED", err.Error(), nil, true)
	}

	embedding, err := m.deps.Embedder.Embed(ctx, blob)
	if err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_EMBED_FAILED", err.Error(), map[string]any{"path": path}, true)
	}
	if len(embedding) > shared.MaxEmbeddingDims {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_EMBEDDING_TOO_LARGE", "embedding dimension count exceeds bound", map[string]any{"max_dims": shared.MaxEmbeddingDims}, false)
	}
	if err := ctx.Err(); err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_CONTEXT_CANCELED", err.Error(), nil, true)
	}

	matches, err := m.deps.Index.Search(ctx, embedding, cfg.MaxMatches)
	if err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_INDEX_FAILED", err.Error(), map[string]any{"path": path}, true)
	}
	if len(matches) > cfg.MaxMatches || len(matches) > shared.MaxIndexMatches {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_MATCHES_TOO_LARGE", "index match count exceeds bound", map[string]any{"max_matches": cfg.MaxMatches}, false)
	}
	if err := ctx.Err(); err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_CONTEXT_CANCELED", err.Error(), nil, true)
	}

	primitives, err := m.deps.Extractor.Extract(ctx, ExtractInput{Hash: hash, Path: path, Blob: blob, Embedding: embedding, Matches: matches})
	if err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_EXTRACT_FAILED", err.Error(), map[string]any{"path": path}, true)
	}

	sidecar := shared.Sidecar{Hash: hash, Path: path, Primitives: primitives, Embedding: copyEmbedding(embedding), Matches: copyMatches(matches)}
	if err := shared.ValidateSidecar(sidecar); err != nil {
		return shared.Sidecar{}, err
	}
	if err := m.deps.Writer.WriteSidecar(ctx, sidecar); err != nil {
		return shared.Sidecar{}, shared.NewFailure("MIDAS_SIDECAR_WRITE_FAILED", err.Error(), map[string]any{"path": path, "hash": hash}, true)
	}
	return sidecar, nil
}

func copyEmbedding(values []float64) []float64 {
	out := make([]float64, 0, len(values))
	for index := 0; index < len(values) && index < shared.MaxEmbeddingDims; index++ {
		out = append(out, values[index])
	}
	return out
}

func copyMatches(values []shared.Match) []shared.Match {
	out := make([]shared.Match, 0, len(values))
	for index := 0; index < len(values) && index < shared.MaxIndexMatches; index++ {
		out = append(out, values[index])
	}
	return out
}

func normalizeConfig(cfg Config) Config {
	if cfg.MaxBlobBytes <= 0 {
		cfg.MaxBlobBytes = DefaultMaxBlobBytes
	}
	if cfg.MaxMatches <= 0 || cfg.MaxMatches > shared.MaxIndexMatches {
		cfg.MaxMatches = DefaultMaxMatches
	}
	if cfg.RuntimeCap <= 0 {
		cfg.RuntimeCap = DefaultRuntimeCap
	}
	if cfg.MemoryCapMiB <= 0 {
		cfg.MemoryCapMiB = DefaultMemoryCapMiB
	}
	return cfg
}

func validateConfig(cfg Config) error {
	if cfg.MaxBlobBytes <= 0 {
		return shared.NewFailure("MIDAS_CONFIG_INVALID", "max blob bytes must be positive", nil, false)
	}
	if cfg.MaxMatches <= 0 || cfg.MaxMatches > shared.MaxIndexMatches {
		return shared.NewFailure("MIDAS_CONFIG_INVALID", "max matches must be within shared match bound", map[string]any{"max_matches": shared.MaxIndexMatches}, false)
	}
	if cfg.RuntimeCap <= 0 {
		return shared.NewFailure("MIDAS_CONFIG_INVALID", "runtime cap must be positive", nil, false)
	}
	if cfg.MemoryCapMiB <= 0 {
		return shared.NewFailure("MIDAS_CONFIG_INVALID", "memory cap must be positive", nil, false)
	}
	return nil
}

func validateDependencies(deps Dependencies) error {
	if deps.Reader == nil || deps.Embedder == nil || deps.Index == nil || deps.Extractor == nil || deps.Writer == nil {
		return shared.NewFailure("MIDAS_DEPENDENCY_MISSING", "reader, embedder, index, extractor, and writer dependencies are required", nil, false)
	}
	return nil
}
