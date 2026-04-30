package crypto

import (
	"crypto/ed25519"
	"encoding/hex"
	"errors"
)

func LoadPrivateKeyFromSeedHex(seedHex string) (ed25519.PrivateKey, error) {
	if seedHex == "" {
		return nil, errors.New("missing signing seed")
	}
	seed, err := hex.DecodeString(seedHex)
	if err != nil {
		return nil, err
	}
	if len(seed) != ed25519.SeedSize {
		return nil, errors.New("seed must be 32 bytes hex")
	}
	return ed25519.NewKeyFromSeed(seed), nil
}
