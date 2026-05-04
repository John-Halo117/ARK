package netwatch

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/John-Halo117/ARK/arkfield/internal/stability"
)

type gate struct{ freeze bool }

func (g gate) Evaluate(stability.Observation) stability.Decision {
	return stability.Decision{Freeze: g.freeze, Reason: "guard"}
}

func TestController_BrowserBurstCap(t *testing.T) {
	c, err := New(Config{MaxBrowserBursts: 1}, gate{})
	if err != nil {
		t.Fatal(err)
	}
	r1, err := c.Execute(context.Background(), ActionRequest{Target: "browser", Action: "scan", Source: "test"})
	if err != nil || !r1.Accepted {
		t.Fatalf("expected first browser action accepted, got %+v err=%v", r1, err)
	}
	r2, err := c.Execute(context.Background(), ActionRequest{Target: "browser", Action: "scan", Source: "test"})
	if err != nil || r2.Accepted || r2.Reason != "browser_burst_cap" {
		t.Fatalf("expected burst cap rejection, got %+v err=%v", r2, err)
	}
}

func TestController_StabilityFreezeTriggersS2(t *testing.T) {
	c, err := New(Config{}, gate{freeze: true})
	if err != nil {
		t.Fatal(err)
	}
	res, err := c.Execute(context.Background(), ActionRequest{Target: "browser", Action: "scan", Source: "test"})
	if err != nil {
		t.Fatal(err)
	}
	if !res.S2Fallback || res.Accepted {
		t.Fatalf("expected S2 fallback on freeze, got %+v", res)
	}
}

func TestController_HookExecution(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	c, err := New(Config{PfSenseHookURL: srv.URL}, gate{})
	if err != nil {
		t.Fatal(err)
	}
	res, err := c.Execute(context.Background(), ActionRequest{Target: "pfsense", Action: "apply", Source: "test"})
	if err != nil {
		t.Fatal(err)
	}
	if !res.Accepted {
		t.Fatalf("expected accepted hook execution, got %+v", res)
	}
}
