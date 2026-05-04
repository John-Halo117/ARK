// Package ingestforward provides a Publisher implementation that forwards
// pre-computed CID events to the single-writer ingestion-leader over HTTP
// instead of publishing to NATS directly. This preserves the single-writer
// invariant: the ingestion-leader is the only service that writes to NATS.
package ingestforward

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Forwarder POSTs raw event payloads to the ingestion-leader.
type Forwarder struct {
	Endpoint string
	Client   *http.Client
}

// New returns a Forwarder with a sensible default HTTP client if one isn't set.
func New(endpoint string, timeout time.Duration) Forwarder {
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	return Forwarder{Endpoint: endpoint, Client: &http.Client{Timeout: timeout}}
}

// Publish posts the payload to the configured ingestion-leader endpoint. It
// returns an error if the endpoint is not configured, if the HTTP call fails,
// or if the leader responds with a non-2xx status.
func (f Forwarder) Publish(payload []byte) error {
	endpoint := strings.TrimSpace(f.Endpoint)
	if endpoint == "" {
		return errors.New("ingestion-leader endpoint is not configured")
	}
	client := f.Client
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		_, _ = io.Copy(io.Discard, resp.Body)
		return fmt.Errorf("ingestion-leader rejected forward: status %d", resp.StatusCode)
	}
	return nil
}
