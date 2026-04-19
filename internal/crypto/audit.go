package crypto

import (
	"encoding/json"
	"os"
)

type AuditEntry struct {
	CID     string `json:"cid"`
	Prev    string `json:"prev"`
	Hash    string `json:"hash"`
}

func AppendAudit(path string, cid string, prev string) (AuditEntry, error) {
	hash := CSHAKE256Hex("ARK_AUDIT", []byte(cid+prev))
	entry := AuditEntry{CID: cid, Prev: prev, Hash: hash}
	b, _ := json.Marshal(entry)
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return entry, err
	}
	defer f.Close()
	f.Write(append(b, '\n'))
	return entry, nil
}
