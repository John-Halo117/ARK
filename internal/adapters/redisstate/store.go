package redisstate

import (
	"encoding/json"
	"errors"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/ingestion"
	"github.com/John-Halo117/ARK/arkfield/internal/transport"
)

const pendingMarker = "__pending__"

type Store struct {
	Client       *transport.RedisClient
	DedupePrefix string
	SequenceKey  string
	PendingTTL   time.Duration
}

func (s *Store) key(stateHash string) string { return s.DedupePrefix + stateHash }

func (s *Store) Reserve(stateHash string) (bool, error) {
	if s.Client == nil {
		return false, errors.New("redis client is nil")
	}
	ttl := int(s.PendingTTL.Seconds())
	if ttl <= 0 {
		ttl = 30
	}
	return s.Client.SetNXEX(s.key(stateHash), pendingMarker, ttl)
}

func (s *Store) Get(stateHash string) (ingestion.DedupeRecord, bool, bool, error) {
	if s.Client == nil {
		return ingestion.DedupeRecord{}, false, false, errors.New("redis client is nil")
	}
	v, found, err := s.Client.Get(s.key(stateHash))
	if err != nil || !found {
		return ingestion.DedupeRecord{}, false, false, err
	}
	if v == pendingMarker {
		return ingestion.DedupeRecord{}, false, true, nil
	}
	var rec ingestion.DedupeRecord
	if err := json.Unmarshal([]byte(v), &rec); err != nil {
		return ingestion.DedupeRecord{}, false, false, err
	}
	return rec, true, false, nil
}

func (s *Store) Commit(stateHash string, rec ingestion.DedupeRecord) error {
	raw, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	return s.Client.Set(s.key(stateHash), string(raw))
}

func (s *Store) Release(stateHash string) error {
	return s.Client.Del(s.key(stateHash))
}

func (s *Store) NextSequence() (uint64, error) {
	if s.Client == nil {
		return 0, errors.New("redis client is nil")
	}
	return s.Client.Incr(s.SequenceKey)
}
