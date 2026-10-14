package http_test

import (
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"

	sehttp "github.com/mb-89/SE/src/internal/io/http"
)

// routine is a fake routine trigger on a local listener: it takes a fire that
// carries the trigger's headers and token, limit times, then rate limits.
func routine(t *testing.T, token string, limit int) (string, func() int) {
	t.Helper()
	var mu sync.Mutex
	fired := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		mu.Lock()
		defer mu.Unlock()
		switch {
		case r.Method != http.MethodPost || r.URL.Path != "/fire" || string(body) != "{}" ||
			r.Header.Get("anthropic-beta") != "experimental-cc-routine-2026-04-01" ||
			r.Header.Get("anthropic-version") != "2023-06-01" ||
			r.Header.Get("Content-Type") != "application/json":
			w.WriteHeader(http.StatusBadRequest)
			io.WriteString(w, `{"type":"error","error":{"type":"invalid_request_error"}}`)
		case r.Header.Get("Authorization") != "Bearer "+token:
			w.WriteHeader(http.StatusUnauthorized)
			io.WriteString(w, `{"type":"error","error":{"type":"authentication_error"}}`)
		case fired >= limit:
			w.WriteHeader(http.StatusTooManyRequests)
			io.WriteString(w, `{"type":"error","error":{"type":"rate_limit_error"}}`)
		default:
			fired++
			io.WriteString(w, `{"type":"routine_fire","claude_code_session_url":"https://claude.ai/code/session_x"}`)
		}
	}))
	t.Cleanup(srv.Close)
	return srv.URL + "/fire", func() int { mu.Lock(); defer mu.Unlock(); return fired }
}

func TestTheRealNetKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) world {
		return world{net: sehttp.Real(), routine: func(token string, limit int) (string, func() int) {
			return routine(t, token, limit)
		}}
	})
}
