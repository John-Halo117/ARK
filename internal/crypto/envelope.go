package crypto

import (
	"crypto/ed25519"
	"encoding/json"
)

type Envelope struct {
	CID       string `json:"cid"`
	Payload   []byte `json:"payload"`
	Signature []byte `json:"signature"`
	PubKey    []byte `json:"pubkey"`
}

func SignEnvelope(priv ed25519.PrivateKey, payload []byte) (Envelope, error) {
	cid := CSHAKE256Hex("ARK_EVENT", payload)
	sig := ed25519.Sign(priv, payload)
	return Envelope{
		CID: cid,
		Payload: payload,
		Signature: sig,
		PubKey: priv.Public().(ed25519.PublicKey),
	}, nil
}

func VerifyEnvelope(env Envelope) bool {
	return ed25519.Verify(env.PubKey, env.Payload, env.Signature)
}

func Encode(env Envelope) ([]byte, error) {
	return json.Marshal(env)
}
