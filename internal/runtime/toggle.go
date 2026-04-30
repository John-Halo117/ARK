package runtime

import (
	"encoding/json"
	"net/http"
	"sync"
)

type Toggle struct {
	Name    string `json:"name"`
	Current bool   `json:"current"`
	Next    bool   `json:"next"`
	Reason  string `json:"reason,omitempty"`
}

type ToggleStore struct {
	mu    sync.RWMutex
	state map[string]bool
}

func NewToggleStore(initial map[string]bool) *ToggleStore {
	cp := map[string]bool{}
	for k, v := range initial {
		cp[k] = v
	}
	return &ToggleStore{state: cp}
}

func (s *ToggleStore) View(name string) Toggle {
	s.mu.RLock()
	defer s.mu.RUnlock()
	cur := s.state[name]
	return Toggle{Name: name, Current: cur, Next: !cur}
}

func (s *ToggleStore) Set(name string, next bool, reason string) Toggle {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.state[name] = next
	return Toggle{Name: name, Current: next, Next: !next, Reason: reason}
}

func (s *ToggleStore) Snapshot() []Toggle {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Toggle, 0, len(s.state))
	for k, v := range s.state {
		out = append(out, Toggle{Name: k, Current: v, Next: !v})
	}
	return out
}

func WriteJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}
