package wiring

import (
	"testing"

	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

type pub struct{ count int }

func (p *pub) Publish([]byte) error { p.count++; return nil }

type gate struct{ freeze bool }

func (g gate) Evaluate(stability.Observation) stability.Decision {
	return stability.Decision{Freeze: g.freeze}
}

func TestMQTTBridgeForward(t *testing.T) {
	p := &pub{}
	b := MQTTBridge{Publisher: p, Gate: gate{}}
	evt, err := b.Forward(MQTTMessage{Topic: "sensor/temp", Payload: []byte("22")})
	if err != nil {
		t.Fatal(err)
	}
	if evt.CID == "" || p.count != 1 {
		t.Fatalf("expected cid and publish, got event=%+v count=%d", evt, p.count)
	}
}

func TestMQTTBridgeFreezeRejected(t *testing.T) {
	b := MQTTBridge{Publisher: &pub{}, Gate: gate{freeze: true}}
	if _, err := b.Forward(MQTTMessage{Topic: "sensor/temp", Payload: []byte("22")}); err == nil {
		t.Fatal("expected freeze rejection")
	}
}
