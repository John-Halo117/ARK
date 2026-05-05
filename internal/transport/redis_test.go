package transport

import (
	"bufio"
	"net"
	"testing"
	"time"
)

func TestRedisClientPingAndSetNXEX(t *testing.T) {
	clientConn, serverConn := net.Pipe()
	defer func() { _ = clientConn.Close() }()
	defer func() { _ = serverConn.Close() }()

	c := &RedisClient{conn: clientConn, rw: bufio.NewReadWriter(bufio.NewReader(clientConn), bufio.NewWriter(clientConn))}

	done := make(chan struct{})
	go func() {
		defer close(done)
		buf := make([]byte, 4096)
		_, _ = serverConn.Read(buf)
		_, _ = serverConn.Write([]byte("+PONG\r\n"))
		_, _ = serverConn.Read(buf)
		_, _ = serverConn.Write([]byte("+OK\r\n"))
	}()

	if err := c.Ping(); err != nil {
		t.Fatalf("ping failed: %v", err)
	}
	ok, err := c.SetNXEX("k", "v", 5)
	if err != nil || !ok {
		t.Fatalf("setnxex expected true nil, got ok=%v err=%v", ok, err)
	}
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("server goroutine timeout")
	}
}
