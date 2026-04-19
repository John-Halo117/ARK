package cryptofabric

import (
	"crypto/sha3"
	"encoding/hex"
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type IndexEntry struct {
	CID       string    `json:"cid"`
	Path      string    `json:"path"`
	SizeBytes int64     `json:"size_bytes"`
	ModTime   time.Time `json:"mod_time"`
	ValidCID  bool      `json:"valid_cid"`
}

type Fabric struct {
	CASRoot string
}

func (f Fabric) VerifyCIDFromBytes(raw []byte, expectedCID string) bool {
	if strings.TrimSpace(expectedCID) == "" {
		return false
	}
	h := sha3.NewCSHAKE256([]byte("ARK-Field-CID"), []byte("git-event"))
	_, _ = h.Write(raw)
	out := make([]byte, 32)
	_, _ = h.Read(out)
	actual := hex.EncodeToString(out)
	return strings.EqualFold(actual, expectedCID)
}

func (f Fabric) VerifyCIDFromFile(path string, expectedCID string) (bool, error) {
	file, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer func() { _ = file.Close() }()
	raw, err := io.ReadAll(file)
	if err != nil {
		return false, err
	}
	return f.VerifyCIDFromBytes(raw, expectedCID), nil
}

func (f Fabric) IndexCAS() ([]IndexEntry, error) {
	if strings.TrimSpace(f.CASRoot) == "" {
		return nil, errors.New("cas root is required")
	}
	entries := make([]IndexEntry, 0, 128)
	err := filepath.WalkDir(f.CASRoot, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		cid := filepath.Base(path)
		info, statErr := d.Info()
		if statErr != nil {
			return statErr
		}
		ok, verifyErr := f.VerifyCIDFromFile(path, cid)
		if verifyErr != nil {
			ok = false
		}
		entries = append(entries, IndexEntry{
			CID:       cid,
			Path:      path,
			SizeBytes: info.Size(),
			ModTime:   info.ModTime().UTC(),
			ValidCID:  ok,
		})
		return nil
	})
	if err != nil {
		return nil, err
	}
	return entries, nil
}
