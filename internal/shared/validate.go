package shared

import "math"

func ValidateHash(hash string) error {
	if hash == "" {
		return NewFailure("HASH_REQUIRED", "hash is required", nil, false)
	}
	if len(hash) > MaxHashBytes {
		return NewFailure("HASH_TOO_LARGE", "hash exceeds bounded length", map[string]any{"max_bytes": MaxHashBytes}, false)
	}
	return nil
}

func ValidatePath(path string) error {
	if path == "" {
		return NewFailure("PATH_REQUIRED", "path is required", nil, false)
	}
	if len(path) > MaxPathBytes {
		return NewFailure("PATH_TOO_LARGE", "path exceeds bounded length", map[string]any{"max_bytes": MaxPathBytes}, false)
	}
	return nil
}

func ValidatePrimitive(p Primitive) error {
	if p.ID == "" {
		return NewFailure("PRIMITIVE_ID_REQUIRED", "primitive id is required", nil, false)
	}
	if len(p.ID) > MaxPrimitiveID {
		return NewFailure("PRIMITIVE_ID_TOO_LARGE", "primitive id exceeds bounded length", map[string]any{"max_bytes": MaxPrimitiveID}, false)
	}
	if !finite(p.Value) || !finite(p.Quality) || !finite(p.Cost) || !finite(p.Time) || !finite(p.Influence) {
		return NewFailure("PRIMITIVE_NUMERIC_INVALID", "primitive numeric fields must be finite", map[string]any{"primitive_id": p.ID}, false)
	}
	if p.Cost < 0 || p.Time < 0 {
		return NewFailure("PRIMITIVE_COST_INVALID", "primitive cost and time must be non-negative", map[string]any{"primitive_id": p.ID}, false)
	}
	if p.Quality < 0 {
		return NewFailure("PRIMITIVE_QUALITY_INVALID", "primitive quality must be non-negative", map[string]any{"primitive_id": p.ID}, false)
	}
	if p.Influence < 0 {
		return NewFailure("PRIMITIVE_INFLUENCE_INVALID", "primitive influence must be non-negative", map[string]any{"primitive_id": p.ID}, false)
	}
	if len(p.Labels) > MaxSemanticLabels {
		return NewFailure("PRIMITIVE_LABELS_TOO_LARGE", "primitive label count exceeds bound", map[string]any{"max_labels": MaxSemanticLabels}, false)
	}
	for index := 0; index < len(p.Labels) && index < MaxSemanticLabels; index++ {
		if len(p.Labels[index]) > MaxSemanticLabel {
			return NewFailure("PRIMITIVE_LABEL_TOO_LARGE", "primitive label exceeds bounded length", map[string]any{"max_bytes": MaxSemanticLabel, "index": index}, false)
		}
	}
	return nil
}

func ValidatePrimitives(primitives []Primitive) error {
	if len(primitives) > MaxPrimitiveCount {
		return NewFailure("PRIMITIVES_TOO_LARGE", "primitive count exceeds bound", map[string]any{"max_primitives": MaxPrimitiveCount}, false)
	}
	for index := 0; index < len(primitives) && index < MaxPrimitiveCount; index++ {
		if err := ValidatePrimitive(primitives[index]); err != nil {
			return err
		}
	}
	return nil
}

func ValidateScore(score Score) error {
	if score.PrimitiveID == "" {
		return NewFailure("SCORE_ID_REQUIRED", "score primitive id is required", nil, false)
	}
	if !finite(score.Value) || !finite(score.Quality) || !finite(score.Cost) || !finite(score.Time) || !finite(score.Influence) || !finite(score.Score) {
		return NewFailure("SCORE_NUMERIC_INVALID", "score numeric fields must be finite", map[string]any{"primitive_id": score.PrimitiveID}, false)
	}
	if score.Cost < 0 || score.Time < 0 || score.Influence < 0 {
		return NewFailure("SCORE_RANGE_INVALID", "score cost, time, and influence must be non-negative", map[string]any{"primitive_id": score.PrimitiveID}, false)
	}
	return nil
}

func ValidateScores(scores []Score) error {
	if len(scores) > MaxPrimitiveCount {
		return NewFailure("SCORES_TOO_LARGE", "score count exceeds bound", map[string]any{"max_scores": MaxPrimitiveCount}, false)
	}
	for index := 0; index < len(scores) && index < MaxPrimitiveCount; index++ {
		if err := ValidateScore(scores[index]); err != nil {
			return err
		}
	}
	return nil
}

func ValidateSidecar(sidecar Sidecar) error {
	if err := ValidateHash(sidecar.Hash); err != nil {
		return err
	}
	if err := ValidatePath(sidecar.Path); err != nil {
		return err
	}
	if err := ValidatePrimitives(sidecar.Primitives); err != nil {
		return err
	}
	if len(sidecar.Embedding) > MaxEmbeddingDims {
		return NewFailure("SIDECAR_EMBEDDING_TOO_LARGE", "embedding dimension count exceeds bound", map[string]any{"max_dims": MaxEmbeddingDims}, false)
	}
	for index := 0; index < len(sidecar.Embedding) && index < MaxEmbeddingDims; index++ {
		if !finite(sidecar.Embedding[index]) {
			return NewFailure("SIDECAR_EMBEDDING_INVALID", "embedding values must be finite", map[string]any{"index": index}, false)
		}
	}
	if len(sidecar.Matches) > MaxIndexMatches {
		return NewFailure("SIDECAR_MATCHES_TOO_LARGE", "match count exceeds bound", map[string]any{"max_matches": MaxIndexMatches}, false)
	}
	for index := 0; index < len(sidecar.Matches) && index < MaxIndexMatches; index++ {
		if sidecar.Matches[index].ID == "" {
			return NewFailure("SIDECAR_MATCH_ID_REQUIRED", "match id is required", map[string]any{"index": index}, false)
		}
		if len(sidecar.Matches[index].ID) > MaxMatchID {
			return NewFailure("SIDECAR_MATCH_ID_TOO_LARGE", "match id exceeds bounded length", map[string]any{"max_bytes": MaxMatchID, "index": index}, false)
		}
		if !finite(sidecar.Matches[index].Similarity) {
			return NewFailure("SIDECAR_MATCH_INVALID", "match similarity must be finite", map[string]any{"index": index}, false)
		}
	}
	return nil
}

func finite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}
