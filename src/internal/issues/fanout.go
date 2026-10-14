package issues

import (
	"encoding/json"
	"fmt"
	"strings"

	sehttp "github.com/mb-89/SE/src/internal/io/http"
)

// The environment variables that name the routine's API trigger: its fire URL
// and its bearer token.
const (
	FireURLVar   = "SE_ROUTINE_FIRE_URL"
	FireTokenVar = "SE_ROUTINE_FIRE_TOKEN"
)

// Fire fires the routine once through its API trigger, so another box starts
// and takes the next ready issue: the fan-out every claim does. It never fails
// the claim: it answers one line saying what happened, a refused or failed
// fire included. getenv reads the two variables; a missing one turns fan-out
// off. The token is never part of the answer.
func Fire(getenv func(string) string, net sehttp.Net) string {
	url, token := getenv(FireURLVar), getenv(FireTokenVar)
	if url == "" || token == "" {
		return fmt.Sprintf("Fan-out is off: %s and %s are not both set.", FireURLVar, FireTokenVar)
	}
	answer, err := net.Fire(url, token)
	if err != nil {
		return fmt.Sprintf("Fan-out failed: %v", hide(err, token))
	}
	if !answer.OK() {
		return fmt.Sprintf("Fan-out refused: %s %s", sehttp.StatusText(answer.Status), hide(fmt.Errorf("%s", brief(answer.Body)), token))
	}
	if u := sessionURL(answer.Body); u != "" {
		return "Fan-out fired the routine: " + u
	}
	return "Fan-out fired the routine: " + hide(fmt.Errorf("%s", brief(answer.Body)), token).Error()
}

// sessionURL finds the started session's link in the fire's answer: the first
// string field whose name ends in url.
func sessionURL(body []byte) string {
	var answer map[string]any
	if json.Unmarshal(body, &answer) != nil {
		return ""
	}
	for _, key := range []string{"claude_code_session_url", "session_url", "url"} {
		if s, ok := answer[key].(string); ok && s != "" {
			return s
		}
	}
	for key, v := range answer {
		if s, ok := v.(string); ok && s != "" && strings.HasSuffix(strings.ToLower(key), "url") {
			return s
		}
	}
	return ""
}

// brief is the answer's body on one line, cut short.
func brief(body []byte) string {
	s := strings.Join(strings.Fields(string(body)), " ")
	if len(s) > 300 {
		s = s[:300] + "…"
	}
	return s
}

// hide keeps the token out of anything se prints.
func hide(err error, token string) error {
	return fmt.Errorf("%s", strings.ReplaceAll(err.Error(), token, "<token>"))
}
