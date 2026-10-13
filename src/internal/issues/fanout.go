package issues

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
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
func Fire(getenv func(string) string, client *http.Client) string {
	url, token := getenv(FireURLVar), getenv(FireTokenVar)
	if url == "" || token == "" {
		return fmt.Sprintf("Fan-out is off: %s and %s are not both set.", FireURLVar, FireTokenVar)
	}
	req, err := http.NewRequest(http.MethodPost, url, strings.NewReader("{}"))
	if err != nil {
		return fmt.Sprintf("Fan-out failed: %v", hide(err, token))
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("anthropic-beta", "experimental-cc-routine-2026-04-01")
	req.Header.Set("anthropic-version", "2023-06-01")
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Sprintf("Fan-out failed: %v", hide(err, token))
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if resp.StatusCode/100 != 2 {
		return fmt.Sprintf("Fan-out refused: %s %s", resp.Status, hide(fmt.Errorf("%s", brief(body)), token))
	}
	if u := sessionURL(body); u != "" {
		return "Fan-out fired the routine: " + u
	}
	return "Fan-out fired the routine: " + hide(fmt.Errorf("%s", brief(body)), token).Error()
}

// FireFromEnv is Fire with this process's environment and a client that gives
// up after 30 seconds.
func FireFromEnv() string {
	return Fire(os.Getenv, &http.Client{Timeout: 30 * time.Second})
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
