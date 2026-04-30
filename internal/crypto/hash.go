package crypto

import (
	"crypto/sha3"
	"encoding/hex"
)

func CSHAKE256Hex(domain string, payload []byte) string {
	h := sha3.NewCSHAKE256([]byte(domain), []byte("ARK"))
	h.Write(payload)
	out := make([]byte, 32)
	h.Read(out)
	return hex.EncodeToString(out)
}

func MerkleRootHex(domain string, leaves []string) string {
	if len(leaves) == 0 {
		return CSHAKE256Hex(domain, []byte(""))
	}
	level := append([]string(nil), leaves...)
	for len(level) > 1 {
		next := []string{}
		for i := 0; i < len(level); i += 2 {
			left := level[i]
			right := left
			if i+1 < len(level) {
				right = level[i+1]
			}
			next = append(next, CSHAKE256Hex(domain, []byte(left+":"+right)))
		}
		level = next
	}
	return level[0]
}
