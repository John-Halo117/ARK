package cryptofabric

import (
	"crypto/sha3"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

func cidFor(raw []byte) string {
	h := sha3.NewCSHAKE256([]byte("ARK-Field-CID"), []byte("git-event"))
	_, _ = h.Write(raw)
	out := make([]byte, 32)
	_, _ = h.Read(out)
	return hex.EncodeToString(out)
}

func TestVerifyCIDAndIndexCAS(t *testing.T) {
	dir := t.TempDir()
	raw := []byte("payload")
	cid := cidFor(raw)
	path := filepath.Join(dir, cid[:2], cid[2:4])
	if err := os.MkdirAll(path, 0o755); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(path, cid)
	if err := os.WriteFile(file, raw, 0o644); err != nil {
		t.Fatal(err)
	}

	f := Fabric{CASRoot: dir}
	ok, err := f.VerifyCIDFromFile(file, cid)
	if err != nil || !ok {
		t.Fatalf("expected cid verification success, ok=%v err=%v", ok, err)
	}
	entries, err := f.IndexCAS()
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || !entries[0].ValidCID {
		t.Fatalf("expected one valid index entry, got %+v", entries)
	}
}
