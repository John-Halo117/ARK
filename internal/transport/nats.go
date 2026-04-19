package transport

import (
	"bufio"
	"fmt"
	"net"
	"net/url"
	"strings"
	"time"
)

type NATSClient struct {
	conn net.Conn
	rw   *bufio.ReadWriter
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
