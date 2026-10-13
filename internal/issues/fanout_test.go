package issues

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// fake is a routine trigger that answers status and body and records each fire.
func fake(t *testing.T, status int, body string) (url string, fires *[]*http.Request, bodies *[]string) {
	t.Helper()
	fires, bodies = &[]*http.Request{}, &[]string{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		*fires, *bodies = append(*fires, r), append(*bodies, string(b))
		w.WriteHeader(status)
		io.WriteString(w, body)
	}))
	t.Cleanup(srv.Close)
	return srv.URL + "/fire", fires, bodies
}

func env(vars map[string]string) func(string) string {
	return func(k string) string { return vars[k] }
}

func TestAFireCarriesTheTriggersHeaders(t *testing.T) {
	url, fires, bodies := fake(t, 200, `{"type":"routine_fire","claude_code_session_url":"https://claude.ai/code/session_x"}`)
	note := Fire(env(map[string]string{FireURLVar: url, FireTokenVar: "sekrit"}), http.DefaultClient)
	if note != "Fan-out fired the routine: https://claude.ai/code/session_x" {
		t.Fatalf("%q", note)
	}
	if len(*fires) != 1 {
		t.Fatalf("%d fires", len(*fires))
	}
	r := (*fires)[0]
	for h, want := range map[string]string{
		"Authorization":     "Bearer sekrit",
		"anthropic-beta":    "experimental-cc-routine-2026-04-01",
		"anthropic-version": "2023-06-01",
		"Content-Type":      "application/json",
	} {
		if got := r.Header.Get(h); got != want {
			t.Errorf("%s: %q, want %q", h, got, want)
		}
	}
	if r.Method != http.MethodPost || r.URL.Path != "/fire" || (*bodies)[0] != "{}" {
		t.Errorf("%s %s %q", r.Method, r.URL.Path, (*bodies)[0])
	}
}

func TestUnsetVariablesTurnFanOutOff(t *testing.T) {
	url, fires, _ := fake(t, 200, `{}`)
	for _, vars := range []map[string]string{{}, {FireURLVar: url}, {FireTokenVar: "sekrit"}} {
		if note := Fire(env(vars), http.DefaultClient); !strings.HasPrefix(note, "Fan-out is off") || strings.Contains(note, "sekrit") {
			t.Errorf("%v: %q", vars, note)
		}
	}
	if len(*fires) != 0 {
		t.Fatalf("%d fires", len(*fires))
	}
}

func TestARefusedOrFailedFireIsReported(t *testing.T) {
	url, _, _ := fake(t, 429, `{"error":{"type":"rate_limit_error","message":"sekrit fires an hour"}}`)
	note := Fire(env(map[string]string{FireURLVar: url, FireTokenVar: "sekrit"}), http.DefaultClient)
	if !strings.HasPrefix(note, "Fan-out refused: 429") || strings.Contains(note, "sekrit") {
		t.Fatalf("%q", note)
	}
	note = Fire(env(map[string]string{FireURLVar: "http://127.0.0.1:1/sekrit", FireTokenVar: "sekrit"}), http.DefaultClient)
	if !strings.HasPrefix(note, "Fan-out failed:") || strings.Contains(note, "sekrit") {
		t.Fatalf("%q", note)
	}
}
