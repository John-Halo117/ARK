package transport

import (
	"bufio"
	"errors"
	"fmt"
	"net"
	"strconv"
	"strings"
	"sync"
	"time"
)

type RedisClient struct {
	mu   sync.Mutex
	conn net.Conn
	rw   *bufio.ReadWriter
}

func NewRedisClient(addr string, timeout time.Duration) (*RedisClient, error) {
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return nil, err
	}
	return &RedisClient{conn: conn, rw: bufio.NewReadWriter(bufio.NewReader(conn), bufio.NewWriter(conn))}, nil
}

func (c *RedisClient) Close() error { return c.conn.Close() }

func (c *RedisClient) Ping() error {
	resp, err := c.cmd("PING")
	if err != nil {
		return err
	}
	if resp != "PONG" {
		return fmt.Errorf("unexpected ping response: %s", resp)
	}
	return nil
}

func (c *RedisClient) Get(key string) (string, bool, error) {
	resp, err := c.cmd("GET", key)
	if err != nil {
		if errors.Is(err, errRedisNil) {
			return "", false, nil
		}
		return "", false, err
	}
	return resp, true, nil
}

func (c *RedisClient) Set(key, value string) error {
	resp, err := c.cmd("SET", key, value)
	if err != nil {
		return err
	}
	if resp != "OK" {
		return fmt.Errorf("unexpected set response: %s", resp)
	}
	return nil
}

func (c *RedisClient) Incr(key string) (uint64, error) {
	resp, err := c.cmd("INCR", key)
	if err != nil {
		return 0, err
	}
	n, err := strconv.ParseUint(resp, 10, 64)
	if err != nil {
		return 0, err
	}
	return n, nil
}

var errRedisNil = errors.New("redis nil")

func (c *RedisClient) cmd(parts ...string) (string, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if _, err := fmt.Fprintf(c.rw, "*%d\r\n", len(parts)); err != nil {
		return "", err
	}
	for _, p := range parts {
		if _, err := fmt.Fprintf(c.rw, "$%d\r\n%s\r\n", len(p), p); err != nil {
			return "", err
		}
	}
	if err := c.rw.Flush(); err != nil {
		return "", err
	}

	line, err := c.rw.ReadString('\n')
	if err != nil {
		return "", err
	}
	line = strings.TrimSuffix(line, "\r\n")
	if len(line) == 0 {
		return "", errors.New("empty redis response")
	}

	switch line[0] {
	case '+', ':':
		return line[1:], nil
	case '$':
		sz, err := strconv.Atoi(line[1:])
		if err != nil {
			return "", err
		}
		if sz == -1 {
			return "", errRedisNil
		}
		buf := make([]byte, sz+2)
		if _, err := c.rw.Read(buf); err != nil {
			return "", err
		}
		return string(buf[:sz]), nil
	case '-':
		if strings.HasPrefix(line, "-ERR") {
			return "", errors.New(strings.TrimSpace(line[4:]))
		}
		return "", errors.New(line[1:])
	default:
		return "", fmt.Errorf("unsupported redis response: %q", line)
	}
}
