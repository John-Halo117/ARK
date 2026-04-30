package gsb

import (
	"context"
	"sync"
	"time"

	"github.com/John-Halo117/ARK/arkfield/core"
)

const (
	MaxTopics           = 32
	MaxSubscribers      = 16
	MaxMessagesPerTopic = 128
	MaxMessageBytes     = 1 << 20
)

type Handler func(context.Context, Message) error

type Message struct {
	Topic       string    `json:"topic"`
	Payload     []byte    `json:"payload"`
	PublishedAt time.Time `json:"published_at"`
}

type Bus interface {
	Publish(context.Context, string, []byte) error
	Subscribe(string, Handler) error
	Replay(context.Context, string, int, Handler) error
	Health() core.HealthStatus
}

type MemoryBus struct {
	mu          sync.Mutex
	messages    map[string][]Message
	subscribers map[string][]Handler
	now         func() time.Time
}

func NewMemoryBus(now func() time.Time) *MemoryBus {
	if now == nil {
		now = func() time.Time { return time.Now().UTC() }
	}
	return &MemoryBus{messages: map[string][]Message{}, subscribers: map[string][]Handler{}, now: now}
}

func (b *MemoryBus) Health() core.HealthStatus {
	return core.HealthStatus{Status: "ok", Module: "gsb.memory", RuntimeCap: 50 * time.Millisecond, MemoryCapMiB: 16}
}

func (b *MemoryBus) Publish(ctx context.Context, topic string, payload []byte) error {
	if topic == "" {
		return core.NewFailure("GSB_TOPIC_REQUIRED", "topic is required", nil, false)
	}
	if len(payload) > MaxMessageBytes {
		return core.NewFailure("GSB_PAYLOAD_TOO_LARGE", "payload exceeds bounded byte size", map[string]any{"max_bytes": MaxMessageBytes}, false)
	}
	b.mu.Lock()
	if len(b.messages) >= MaxTopics {
		if _, ok := b.messages[topic]; !ok {
			b.mu.Unlock()
			return core.NewFailure("GSB_TOPIC_LIMIT", "topic count exceeds bounded capacity", map[string]any{"max_topics": MaxTopics}, true)
		}
	}
	message := Message{Topic: topic, Payload: append([]byte(nil), payload...), PublishedAt: b.now()}
	stream := append(b.messages[topic], message)
	if len(stream) > MaxMessagesPerTopic {
		start := len(stream) - MaxMessagesPerTopic
		stream = append([]Message(nil), stream[start:]...)
	}
	b.messages[topic] = stream
	handlers := append([]Handler(nil), b.subscribers[topic]...)
	b.mu.Unlock()

	for i := 0; i < len(handlers) && i < MaxSubscribers; i++ {
		if err := handlers[i](ctx, message); err != nil {
			return err
		}
	}
	return nil
}

func (b *MemoryBus) Subscribe(topic string, handler Handler) error {
	if topic == "" || handler == nil {
		return core.NewFailure("GSB_SUBSCRIPTION_INVALID", "topic and handler are required", nil, false)
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if len(b.messages) >= MaxTopics {
		if _, ok := b.messages[topic]; !ok {
			return core.NewFailure("GSB_TOPIC_LIMIT", "topic count exceeds bounded capacity", map[string]any{"max_topics": MaxTopics}, true)
		}
	}
	existing := b.subscribers[topic]
	if len(existing) >= MaxSubscribers {
		return core.NewFailure("GSB_SUBSCRIBER_LIMIT", "subscriber count exceeds bounded capacity", map[string]any{"max_subscribers": MaxSubscribers}, true)
	}
	b.subscribers[topic] = append(existing, handler)
	if _, ok := b.messages[topic]; !ok {
		b.messages[topic] = []Message{}
	}
	return nil
}

func (b *MemoryBus) Replay(ctx context.Context, topic string, limit int, handler Handler) error {
	if topic == "" || handler == nil {
		return core.NewFailure("GSB_REPLAY_INVALID", "topic and handler are required", nil, false)
	}
	if limit <= 0 || limit > MaxMessagesPerTopic {
		return core.NewFailure("GSB_REPLAY_LIMIT_INVALID", "replay limit must be within bounded message capacity", map[string]any{"max_messages": MaxMessagesPerTopic}, false)
	}
	b.mu.Lock()
	stream := append([]Message(nil), b.messages[topic]...)
	b.mu.Unlock()
	start := 0
	if len(stream) > limit {
		start = len(stream) - limit
	}
	for i := start; i < len(stream) && i < start+limit; i++ {
		if err := handler(ctx, stream[i]); err != nil {
			return err
		}
	}
	return nil
}
