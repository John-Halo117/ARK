package transport

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"strings"
	"sync"
	"time"
)

type NATSClient struct {
	mu   sync.Mutex
	conn net.Conn
	rw   *bufio.ReadWriter
	sid  uint64
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
	c := &NATSClient{conn: conn, rw: bufio.NewReadWriter(bufio.NewReader(conn), bufio.NewWriter(conn))}
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

	if err := c.drainPing(25 * time.Millisecond); err != nil {
		return err
	}
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
	if timeout <= 0 {
		return nil, errors.New("timeout must be positive")
	}

	c.mu.Lock()
	defer c.mu.Unlock()

	c.sid++
	sid := c.sid
	inbox := fmt.Sprintf("_INBOX.%d", sid)
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
	if _, err := c.rw.WriteString("\r\nPING\r\n"); err != nil {
		return nil, err
	}
	if err := c.rw.Flush(); err != nil {
		return nil, err
	}

	deadline := time.Now().Add(timeout)
	if err := c.conn.SetReadDeadline(deadline); err != nil {
		return nil, err
	}
	defer func() { _ = c.conn.SetReadDeadline(time.Time{}) }()

	for reads := 0; reads < 16; reads++ {
		line, err := c.rw.ReadString('\n')
		if err != nil {
			return nil, err
		}
		fields := strings.Fields(strings.TrimSpace(line))
		if len(fields) == 0 {
			continue
		}
		switch fields[0] {
		case "PING":
			if _, err := c.rw.WriteString("PONG\r\n"); err != nil {
				return nil, err
			}
			if err := c.rw.Flush(); err != nil {
				return nil, err
			}
		case "PONG", "+OK":
			continue
		case "MSG":
			if len(fields) < 4 {
				return nil, fmt.Errorf("malformed nats msg: %s", strings.TrimSpace(line))
			}
			size, err := parseNATSSize(fields[len(fields)-1])
			if err != nil {
				return nil, err
			}
			buf := make([]byte, size+2)
			if _, err := io.ReadFull(c.rw, buf); err != nil {
				return nil, err
			}
			return buf[:size], nil
		default:
			if strings.HasPrefix(fields[0], "-ERR") {
				return nil, errors.New(strings.TrimSpace(line))
			}
		}
	}
	return nil, errors.New("nats request exceeded max protocol reads")
}

func (c *NATSClient) EnsureJetStreamStream(streamName, subject string) error {
	if strings.TrimSpace(streamName) == "" {
		return errors.New("stream_name is required")
	}
	if strings.TrimSpace(subject) == "" {
		return errors.New("subject is required")
	}
	payload := fmt.Sprintf(`{"name":%q,"subjects":[%q]}`, streamName, subject)
	_, err := c.Request("$JS.API.STREAM.CREATE."+streamName, []byte(payload), 5*time.Second)
	return err
}

func (c *NATSClient) drainPing(timeout time.Duration) error {
	if c.conn == nil || c.rw == nil {
		return errors.New("nats client is not initialized")
	}
	if err := c.conn.SetReadDeadline(time.Now().Add(timeout)); err != nil {
		return err
	}
	defer func() { _ = c.conn.SetReadDeadline(time.Time{}) }()

	line, err := c.rw.ReadString('\n')
	if err != nil {
		if ne, ok := err.(net.Error); ok && ne.Timeout() {
			return nil
		}
		return err
	}
	if strings.TrimSpace(line) != "PING" {
		return nil
	}
	if _, err := c.rw.WriteString("PONG\r\n"); err != nil {
		return err
	}
	return c.rw.Flush()
}

func parseNATSSize(v string) (int, error) {
	var size int
	for index := 0; index < len(v); index++ {
		ch := v[index]
		if ch < '0' || ch > '9' {
			return 0, fmt.Errorf("invalid nats size: %q", v)
		}
		size = size*10 + int(ch-'0')
	}
	return size, nil
}
