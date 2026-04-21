package ingestforward

import (
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestForwarderPublishesPayload(t *testing.T) {
	var got []byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatal(err)
		}
		got = body
		w.WriteHeader(http.StatusAccepted)
	}))
	t.Cleanup(srv.Close)

	f := New(srv.URL, time.Second)
	if err := f.Publish([]byte(`{"cid":"abc"}`)); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(got) != `{"cid":"abc"}` {
		t.Fatalf("unexpected payload: %q", string(got))
	}
}

func TestForwarderRejectsMissingEndpoint(t *testing.T) {
	f := Forwarder{}
	if err := f.Publish([]byte("{}")); err == nil {
		t.Fatal("expected error when endpoint is empty")
	}
}

func TestForwarderSurfacesNon2xx(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "nope", http.StatusInternalServerError)
	}))
	t.Cleanup(srv.Close)

	f := New(srv.URL, time.Second)
	if err := f.Publish([]byte("{}")); err == nil {
		t.Fatal("expected non-2xx to surface as error")
	}
}
