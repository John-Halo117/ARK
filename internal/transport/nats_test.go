package transport

import (
	"bufio"
	"io"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestNATSClientRequestAndEnsureStream(t *testing.T) {
	clientConn, serverConn := net.Pipe()
	defer func() { _ = clientConn.Close() }()
	defer func() { _ = serverConn.Close() }()

	serverDone := make(chan struct{})
	go func() {
		defer close(serverDone)
		r := bufio.NewReader(serverConn)
		_, _ = serverConn.Write([]byte("INFO {}\r\n"))
		line1, _ := r.ReadString('\n')
		line2, _ := r.ReadString('\n')
		if !strings.HasPrefix(line1, "CONNECT") || strings.TrimSpace(line2) != "PING" {
			return
		}
		_, _ = serverConn.Write([]byte("PONG\r\n"))

		for i := 0; i < 2; i++ {
			_, _ = r.ReadString('\n') // SUB
			_, _ = r.ReadString('\n') // UNSUB
			pub, _ := r.ReadString('\n')
			parts := strings.Fields(strings.TrimSpace(pub))
			n, _ := strconv.Atoi(parts[len(parts)-1])
			payload := make([]byte, n+2)
			_, _ = io.ReadFull(r, payload)
			_, _ = r.ReadString('\n') // PING
			_, _ = serverConn.Write([]byte("MSG _INBOX.x 1 2\r\n{}\r\nPONG\r\n"))
		}
	}()

	c := &NATSClient{conn: clientConn, rw: bufio.NewReadWriter(bufio.NewReader(clientConn), bufio.NewWriter(clientConn)), sid: 1}
	if err := c.sendConnect(); err != nil {
		t.Fatalf("connect failed: %v", err)
	}
	if _, err := c.Request("subj", []byte("{}"), 2*time.Second); err != nil {
		t.Fatalf("request failed: %v", err)
	}
	if err := c.EnsureJetStreamStream("ARK_EVENTS", "ark.events.cid"); err != nil {
		t.Fatalf("ensure stream failed: %v", err)
	}
	<-serverDone
}

func TestNATSClientPublishDrainsPing(t *testing.T) {
	clientConn, serverConn := net.Pipe()
	defer func() { _ = clientConn.Close() }()
	defer func() { _ = serverConn.Close() }()

	serverDone := make(chan struct{})
	go func() {
		defer close(serverDone)
		r := bufio.NewReader(serverConn)
		_, _ = serverConn.Write([]byte("INFO {}\r\n"))
		_, _ = r.ReadString('\n') // CONNECT
		_, _ = r.ReadString('\n') // PING
		_, _ = serverConn.Write([]byte("PONG\r\n"))

		_, _ = serverConn.Write([]byte("PING\r\n"))
		if pong, _ := r.ReadString('\n'); strings.TrimSpace(pong) != "PONG" {
			return
		}

		pub, _ := r.ReadString('\n')
		if strings.TrimSpace(pub) != "PUB test.subject 2" {
			return
		}
		payload := make([]byte, 4)
		_, _ = io.ReadFull(r, payload) // "ok\r\n"
	}()

	c := &NATSClient{conn: clientConn, rw: bufio.NewReadWriter(bufio.NewReader(clientConn), bufio.NewWriter(clientConn)), sid: 1}
	if err := c.sendConnect(); err != nil {
		t.Fatalf("connect failed: %v", err)
	}
	if err := c.Publish("test.subject", []byte("ok")); err != nil {
		t.Fatalf("publish failed: %v", err)
	}
	<-serverDone
}
