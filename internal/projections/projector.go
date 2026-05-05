package projections

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/John-Halo117/ARK/arkfield/internal/models"
	"github.com/John-Halo117/ARK/arkfield/internal/transport"
)

type Projector struct {
	Redis      *transport.RedisClient
	DuckDBPath string
	mu         sync.Mutex
}

func (p *Projector) Project(event models.Event) error {
	if p.Redis == nil {
		return errors.New("redis client is required")
	}
	raw, err := json.Marshal(event)
	if err != nil {
		return err
	}
	key := projectionKey(event.Sequence)
	if err := p.Redis.Set(key, string(raw)); err != nil {
		return err
	}
	if err := p.appendDuckProjection(raw); err != nil {
		return err
	}
	return nil
}

func (p *Projector) Replay(fromSeq, toSeq uint64) ([]models.Event, error) {
	if p.Redis == nil {
		return nil, errors.New("redis client is required")
	}
	if fromSeq == 0 || toSeq == 0 || toSeq < fromSeq {
		return nil, errors.New("invalid sequence range")
	}
	items := make([]models.Event, 0, toSeq-fromSeq+1)
	for seq := fromSeq; ; seq++ {
		v, ok, err := p.Redis.Get(projectionKey(seq))
		if err != nil {
			return nil, err
		}
		if ok {
			var ev models.Event
			if err := json.Unmarshal([]byte(v), &ev); err == nil {
				items = append(items, ev)
			}
		}
		if seq == toSeq {
			break
		}
	}
	return items, nil
}

func (p *Projector) appendDuckProjection(raw []byte) error {
	path := strings.TrimSpace(p.DuckDBPath)
	if path == "" {
		return nil
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	defer func() { _ = f.Close() }()
	if _, err := f.Write(raw); err != nil {
		return err
	}
	if _, err := f.WriteString("\n"); err != nil {
		return err
	}
	return nil
}

func projectionKey(seq uint64) string {
	return "ark:projection:" + strconv.FormatUint(seq, 10)
}

func ReplayRangeFromQuery(fromRaw, toRaw string) (uint64, uint64, error) {
	from, err := strconv.ParseUint(fromRaw, 10, 64)
	if err != nil {
		return 0, 0, fmt.Errorf("invalid from: %w", err)
	}
	to, err := strconv.ParseUint(toRaw, 10, 64)
	if err != nil {
		return 0, 0, fmt.Errorf("invalid to: %w", err)
	}
	if from == 0 || to == 0 {
		return 0, 0, errors.New("from and to must be >= 1")
	}
	if to < from {
		return 0, 0, errors.New("to must be >= from")
	}
	return from, to, nil
}
