package natspub

import "github.com/John-Halo117/ARK/arkfield/internal/transport"

type Publisher struct {
	Client     *transport.NATSClient
	Subject    string
	StreamName string
}

func (p Publisher) EnsureStream() error {
	if p.StreamName == "" {
		return nil
	}
	return p.Client.EnsureJetStreamStream(p.StreamName, p.Subject)
}

func (p Publisher) Publish(payload []byte) error {
	return p.Client.Publish(p.Subject, payload)
}
