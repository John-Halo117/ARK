package wiring

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

type Publisher interface {
	Publish(payload []byte) error
}

type Gate interface {
	Evaluate(observation stability.Observation) stability.Decision
}

type MQTTMessage struct {
	Topic   string `json:"topic"`
	Payload []byte `json:"payload"`
	Source  string `json:"source"`
}

type CIDEvent struct {
	CID       string    `json:"cid"`
	Topic     string    `json:"topic"`
	Payload   []byte    `json:"payload"`
	StateHash string    `json:"state_hash"`
	Occurred  time.Time `json:"occurred"`
}

type MQTTBridge struct {
	Publisher Publisher
	Gate      Gate
}

func (b MQTTBridge) Forward(msg MQTTMessage) (CIDEvent, error) {
	if b.Publisher == nil || b.Gate == nil {
		return CIDEvent{}, errors.New("publisher and gate are required")
	}
	if msg.Topic == "" {
		return CIDEvent{}, errors.New("topic is required")
	}
	decision := b.Gate.Evaluate(stability.Observation{
		CurrentX:             0.2,
		TargetX:              0.2,
		Alpha:                0.2,
		Elapsed:              time.Second,
		TrustSources:         []stability.TrustSample{{Weight: 1, Value: 0.2}},
		ProbabilityMass:      []float64{0.7, 0.2, 0.1},
		VelocityDivergence:   0,
		RateIn:               1,
		RateOut:              1,
		BackpressureEpsilon:  0.1,
		CurvatureCenter:      0.2,
		CurvatureNeighbors:   []stability.CurvatureNode{{C: 0.2, W: 1}},
		SignalA:              0.2,
		SignalK:              0,
		SignalGradC:          0,
		SoftWeights:          stability.SoftWeights{WA: 0.34, WK: 0.33, WG: 0.33},
		DeltaG:               0,
		DeltaX:               0,
		Sigma:                1,
		CNew:                 0.2,
		COld:                 0.2,
		RecoveryTheta:        0,
		RecoveryLearningRate: 0.01,
		RecoveryLossGradient: 0,
	})
	if decision.Freeze {
		return CIDEvent{}, errors.New("stability gate rejected mqtt event")
	}

	stateRaw := append([]byte(msg.Topic+":"), msg.Payload...)
	hash := sha256.Sum256(stateRaw)
	cid := hex.EncodeToString(hash[:])
	event := CIDEvent{CID: cid, Topic: msg.Topic, Payload: msg.Payload, StateHash: cid, Occurred: time.Now().UTC()}
	raw, err := json.Marshal(event)
	if err != nil {
		return CIDEvent{}, err
	}
	if err := b.Publisher.Publish(raw); err != nil {
		return CIDEvent{}, err
	}
	return event, nil
}
