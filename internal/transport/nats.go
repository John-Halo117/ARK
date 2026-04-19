package transport

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"net"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

type NATSClient struct {
	mu   sync.Mutex
	conn net.Conn
	rw   *bufio.ReadWriter
	sid  int
}

func NewNATSClient(serverURL string, timeout time.Duration) (*NATSClient, error) {
	u, err := url.Parse(serverURL)
	if err != nil {
		return nil, err
	}
	host := u.Host
	if !strings.Contains(host, ":") {
		host += ":4222"
	}
	conn, err := net.DialTimeout("tcp", host, timeout)
	if err != nil {
		return nil, err
	}
	c := &NATSClient{conn: conn, rw: bufio.NewReadWriter(bufio.NewReader(conn), bufio.NewWriter(conn)), sid: 1}
	if err := c.sendConnect(); err != nil {
		_ = c.conn.Close()
		return nil, err
	}
	return c, nil
}

func (c *NATSClient) Close() error { return c.conn.Close() }

func (c *NATSClient) sendConnect() error {
	line, err := c.rw.ReadString('\n')
	if err != nil {
		return err
	}
	if !strings.HasPrefix(line, "INFO") {
		return fmt.Errorf("unexpected nats greeting: %s", strings.TrimSpace(line))
	}
	if _, err := c.rw.WriteString("CONNECT {\"verbose\":false,\"pedantic\":false}\r\n"); err != nil {
		return err
	}
	if _, err := c.rw.WriteString("PING\r\n"); err != nil {
		return err
	}
	if err := c.rw.Flush(); err != nil {
		return err
	}
	resp, err := c.rw.ReadString('\n')
	if err != nil {
		return err
	}
	if strings.TrimSpace(resp) != "PONG" {
		return fmt.Errorf("unexpected nats ping response: %s", strings.TrimSpace(resp))
	}
	return nil
}

func (c *NATSClient) Publish(subject string, payload []byte) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, err := fmt.Fprintf(c.rw, "PUB %s %d\r\n", subject, len(payload)); err != nil {
		return err
	}
	if _, err := c.rw.Write(payload); err != nil {
		return err
	}
	if _, err := c.rw.WriteString("\r\n"); err != nil {
		return err
	}
	return c.rw.Flush()
}

func (c *NATSClient) Request(subject string, payload []byte, timeout time.Duration) ([]byte, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	inbox := fmt.Sprintf("_INBOX.%d.%d", time.Now().UnixNano(), rand.Int63())
	sid := c.sid
	c.sid++

	if _, err := fmt.Fprintf(c.rw, "SUB %s %d\r\n", inbox, sid); err != nil {
		return nil, err
	}
	if _, err := fmt.Fprintf(c.rw, "UNSUB %d 1\r\n", sid); err != nil {
		return nil, err
	}
	if _, err := fmt.Fprintf(c.rw, "PUB %s %s %d\r\n", subject, inbox, len(payload)); err != nil {
		return nil, err
	}
	if _, err := c.rw.Write(payload); err != nil {
		return nil, err
	}
	if _, err := c.rw.WriteString("\r\n"); err != nil {
		return nil, err
	}
	if _, err := c.rw.WriteString("PING\r\n"); err != nil {
		return nil, err
	}
	if err := c.rw.Flush(); err != nil {
		return nil, err
	}

	_ = c.conn.SetReadDeadline(time.Now().Add(timeout))
	defer func() { _ = c.conn.SetReadDeadline(time.Time{}) }()

	for {
		line, err := c.rw.ReadString('\n')
		if err != nil {
			return nil, err
		}
		line = strings.TrimSpace(line)
		if line == "PONG" || line == "+OK" || line == "" {
			continue
		}
		if strings.HasPrefix(line, "-ERR") {
			return nil, errors.New(line)
		}
		if strings.HasPrefix(line, "MSG ") {
			parts := strings.Fields(line)
			if len(parts) < 4 {
				return nil, fmt.Errorf("invalid nats msg line: %s", line)
			}
			lenIdx := len(parts) - 1
			n, err := strconv.Atoi(parts[lenIdx])
			if err != nil {
				return nil, err
			}
			buf := make([]byte, n)
			if _, err := io.ReadFull(c.rw, buf); err != nil {
				return nil, err
			}
			crlf := make([]byte, 2)
			if _, err := io.ReadFull(c.rw, crlf); err != nil {
				return nil, err
			}
			return buf, nil
		}
	}
}

func (c *NATSClient) EnsureJetStreamStream(streamName, subject string) error {
	createSubject := "$JS.API.STREAM.CREATE." + streamName
	payload, _ := json.Marshal(map[string]any{
		"name":     streamName,
		"subjects": []string{subject},
		"storage":  "file",
	})
	resp, err := c.Request(createSubject, payload, 5*time.Second)
	if err != nil {
		return err
	}
	if strings.Contains(string(resp), "stream name already in use") || strings.Contains(string(resp), "already in use") {
		return nil
	}
	if strings.Contains(string(resp), "\"error\"") {
		return fmt.Errorf("jetstream create stream failed: %s", string(resp))
	}
	return nil
}
