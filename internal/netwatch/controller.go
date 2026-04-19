package netwatch

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os/exec"
	"strings"
	"sync"
	"time"

	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

type StabilityGate interface {
	Evaluate(observation stability.Observation) stability.Decision
}

type ActionRequest struct {
	Target  string            `json:"target"`
	Action  string            `json:"action"`
	Source  string            `json:"source"`
	Payload map[string]string `json:"payload,omitempty"`
}

type ActionResult struct {
	Accepted   bool                   `json:"accepted"`
	Reason     string                 `json:"reason,omitempty"`
	S2Fallback bool                   `json:"s2_fallback"`
	Output     map[string]interface{} `json:"output,omitempty"`
}

type Config struct {
	AiderPath         string
	PfSenseHookURL    string
	UniFiHookURL      string
	MaxBrowserBursts  int
	BrowserBurstReset time.Duration
	ExecTimeout       time.Duration
}

type Controller struct {
	cfg         Config
	gate        StabilityGate
	httpClient  *http.Client
	mu          sync.Mutex
	browserUsed int
	windowStart time.Time
}

func New(cfg Config, gate StabilityGate) (*Controller, error) {
	if gate == nil {
		return nil, errors.New("stability gate is required")
	}
	if cfg.MaxBrowserBursts <= 0 {
		cfg.MaxBrowserBursts = 3
	}
	if cfg.BrowserBurstReset <= 0 {
		cfg.BrowserBurstReset = time.Minute
	}
	if cfg.ExecTimeout <= 0 {
		cfg.ExecTimeout = 20 * time.Second
	}
	if cfg.AiderPath == "" {
		cfg.AiderPath = "aider"
	}
	return &Controller{cfg: cfg, gate: gate, httpClient: &http.Client{Timeout: 10 * time.Second}, windowStart: time.Now().UTC()}, nil
}

func (c *Controller) Execute(ctx context.Context, req ActionRequest) (ActionResult, error) {
	if strings.TrimSpace(req.Target) == "" || strings.TrimSpace(req.Action) == "" {
		return ActionResult{}, errors.New("target and action are required")
	}
	decision := c.gate.Evaluate(observationFromAction(req))
	if decision.Freeze {
		return c.S2Baseline(ctx, req, decision.Reason)
	}

	switch strings.ToLower(req.Target) {
	case "aider":
		return c.execAider(ctx, req)
	case "browser":
		return c.execBrowser(req)
	case "pfsense":
		return c.execHook(ctx, c.cfg.PfSenseHookURL, req)
	case "unifi", "unifi-g6":
		return c.execHook(ctx, c.cfg.UniFiHookURL, req)
	default:
		return ActionResult{}, fmt.Errorf("unsupported target: %s", req.Target)
	}
}

func (c *Controller) S2Baseline(_ context.Context, req ActionRequest, reason string) (ActionResult, error) {
	return ActionResult{
		Accepted:   false,
		Reason:     fmt.Sprintf("s2_anchor:%s:%s", req.Target, reason),
		S2Fallback: true,
		Output: map[string]interface{}{
			"mode":            "S2",
			"network_actions": "paused",
			"aider_actions":   "disabled",
		},
	}, nil
}

func (c *Controller) execAider(ctx context.Context, req ActionRequest) (ActionResult, error) {
	msg := req.Payload["message"]
	if strings.TrimSpace(msg) == "" {
		return ActionResult{}, errors.New("aider message payload is required")
	}
	runCtx, cancel := context.WithTimeout(ctx, c.cfg.ExecTimeout)
	defer cancel()
	cmd := exec.CommandContext(runCtx, c.cfg.AiderPath, "--message", msg, "--no-auto-commits")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return ActionResult{Accepted: false, Reason: "aider_exec_failed", Output: map[string]interface{}{"stderr": string(out)}}, nil
	}
	return ActionResult{Accepted: true, Output: map[string]interface{}{"stdout": string(out)}}, nil
}

func (c *Controller) execBrowser(req ActionRequest) (ActionResult, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now().UTC()
	if now.Sub(c.windowStart) > c.cfg.BrowserBurstReset {
		c.windowStart = now
		c.browserUsed = 0
	}
	if c.browserUsed >= c.cfg.MaxBrowserBursts {
		return ActionResult{Accepted: false, Reason: "browser_burst_cap", Output: map[string]interface{}{"max": c.cfg.MaxBrowserBursts}}, nil
	}
	c.browserUsed++
	return ActionResult{Accepted: true, Output: map[string]interface{}{"bursts_used": c.browserUsed, "action": req.Action}}, nil
}

func (c *Controller) execHook(ctx context.Context, endpoint string, req ActionRequest) (ActionResult, error) {
	if strings.TrimSpace(endpoint) == "" {
		return ActionResult{}, errors.New("hook endpoint not configured")
	}
	payload, _ := json.Marshal(req)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(payload))
	if err != nil {
		return ActionResult{}, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return ActionResult{Accepted: false, Reason: "hook_request_failed"}, nil
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode >= 300 {
		return ActionResult{Accepted: false, Reason: fmt.Sprintf("hook_status_%d", resp.StatusCode)}, nil
	}
	return ActionResult{Accepted: true, Output: map[string]interface{}{"status": resp.StatusCode}}, nil
}

func observationFromAction(req ActionRequest) stability.Observation {
	size := float64(len(req.Action) + len(req.Target) + len(req.Source))
	x := size / 200
	if x > 1 {
		x = 1
	}
	return stability.Observation{
		CurrentX:             x,
		TargetX:              x,
		Alpha:                0.2,
		Elapsed:              time.Second,
		TrustSources:         []stability.TrustSample{{Weight: 1, Value: x}},
		ProbabilityMass:      []float64{0.7, 0.2, 0.1},
		VelocityDivergence:   0,
		RateIn:               1,
		RateOut:              1,
		BackpressureEpsilon:  0.1,
		CurvatureCenter:      x,
		CurvatureNeighbors:   []stability.CurvatureNode{{C: x, W: 1}},
		SignalA:              x,
		SignalK:              0,
		SignalGradC:          0,
		SoftWeights:          stability.SoftWeights{WA: 0.34, WK: 0.33, WG: 0.33},
		DeltaG:               0,
		DeltaX:               0,
		Sigma:                1,
		CNew:                 x,
		COld:                 x,
		RecoveryTheta:        0,
		RecoveryLearningRate: 0.01,
		RecoveryLossGradient: 0,
	}
}
