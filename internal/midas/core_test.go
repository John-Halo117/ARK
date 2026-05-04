package midas

import (
	"context"
	"errors"
	"testing"

	"github.com/John-Halo117/ARK/arkfield/internal/shared"
)

type testReader struct {
	blob []byte
}

func (r testReader) ReadCanonical(ctx context.Context, path string, maxBytes int) ([]byte, error) {
	if len(r.blob) > maxBytes {
		return nil, errors.New("too large")
	}
	return r.blob, nil
}

type testEmbedder struct{}

func (e testEmbedder) Embed(ctx context.Context, blob []byte) ([]float64, error) {
	return []float64{float64(len(blob)), 1}, nil
}

type testIndex struct{}

func (i testIndex) Search(ctx context.Context, embedding []float64, limit int) ([]shared.Match, error) {
	return []shared.Match{{ID: "m1", Similarity: 0.75}}, nil
}

type testExtractor struct{}

func (e testExtractor) Extract(ctx context.Context, input ExtractInput) ([]shared.Primitive, error) {
	return []shared.Primitive{{ID: input.Hash, Value: 1, Quality: 1, Cost: 1, Time: 1, Influence: 1}}, nil
}

type testWriter struct {
	wrote bool
}

func (w *testWriter) WriteSidecar(ctx context.Context, sidecar shared.Sidecar) error {
	w.wrote = true
	return nil
}

func TestEnrichWritesSidecarOnly(t *testing.T) {
	writer := &testWriter{}
	core, err := New(Dependencies{Reader: testReader{blob: []byte("canonical")}, Embedder: testEmbedder{}, Index: testIndex{}, Extractor: testExtractor{}, Writer: writer}, Config{})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	sidecar, err := core.Enrich(context.Background(), "hash-1", "/tmp/blob.json")
	if err != nil {
		t.Fatalf("Enrich() error = %v", err)
	}
	if !writer.wrote {
		t.Fatal("WriteSidecar() was not called")
	}
	if sidecar.Hash != "hash-1" || sidecar.Path != "/tmp/blob.json" {
		t.Fatalf("sidecar identity = %#v", sidecar)
	}
	if len(sidecar.Primitives) != 1 || sidecar.Primitives[0].ID != "hash-1" {
		t.Fatalf("sidecar primitives = %#v", sidecar.Primitives)
	}
}
