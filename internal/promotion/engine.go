package promotion

import (
	"encoding/json"
	"os"
	"time"
)

type Record struct {
	Commit    string    `json:"commit"`
	State     string    `json:"state"`
	Timestamp time.Time `json:"timestamp"`
	Reason    string    `json:"reason,omitempty"`
}

func Promote(path, commit string) error {
	rec := Record{
		Commit:    commit,
		State:     "promoted",
		Timestamp: time.Now().UTC(),
	}
	return write(path, rec)
}

func Reject(path, commit, reason string) error {
	rec := Record{
		Commit:    commit,
		State:     "rejected",
		Timestamp: time.Now().UTC(),
		Reason:    reason,
	}
	return write(path, rec)
}

func write(path string, rec Record) error {
	b, _ := json.Marshal(rec)
	return os.WriteFile(path, b, 0644)
}
