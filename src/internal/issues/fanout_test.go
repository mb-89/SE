package issues_test

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/issues"
)

const trigger = "https://api.example/v1/routines/r1/fire"

// routine is a fake network with the routine's trigger standing at trigger,
// taking the token sekrit for limit fires.
func routine(limit int) *http.Fake {
	f := http.NewFake()
	f.Routine(trigger, "sekrit", limit)
	return f
}

func env(vars map[string]string) func(string) string {
	return func(k string) string { return vars[k] }
}

func TestAFireNamesTheSessionItStarted(t *testing.T) {
	f := routine(1)
	note := issues.Fire(env(map[string]string{issues.FireURLVar: trigger, issues.FireTokenVar: "sekrit"}), f)
	if note != "Fan-out fired the routine: https://claude.ai/code/session_fake1" || f.Fired(trigger) != 1 {
		t.Fatalf("%q, %d fired", note, f.Fired(trigger))
	}
}

func TestUnsetVariablesTurnFanOutOff(t *testing.T) {
	f := routine(5)
	for _, vars := range []map[string]string{{}, {issues.FireURLVar: trigger}, {issues.FireTokenVar: "sekrit"}} {
		if note := issues.Fire(env(vars), f); !strings.HasPrefix(note, "Fan-out is off") || strings.Contains(note, "sekrit") {
			t.Errorf("%v: %q", vars, note)
		}
	}
	if f.Fired(trigger) != 0 {
		t.Fatalf("%d fires", f.Fired(trigger))
	}
}

func TestARefusedOrFailedFireIsReported(t *testing.T) {
	f := routine(0)
	note := issues.Fire(env(map[string]string{issues.FireURLVar: trigger, issues.FireTokenVar: "sekrit"}), f)
	if !strings.HasPrefix(note, "Fan-out refused: 429 Too Many Requests") || strings.Contains(note, "sekrit") {
		t.Fatalf("%q", note)
	}
	note = issues.Fire(env(map[string]string{issues.FireURLVar: trigger, issues.FireTokenVar: "nope"}), f)
	if !strings.HasPrefix(note, "Fan-out refused: 401 Unauthorized") {
		t.Fatalf("%q", note)
	}
	note = issues.Fire(env(map[string]string{issues.FireURLVar: "https://nowhere.example/sekrit", issues.FireTokenVar: "sekrit"}), f)
	if !strings.HasPrefix(note, "Fan-out failed:") || strings.Contains(note, "sekrit") || !strings.Contains(note, "<token>") {
		t.Fatalf("%q", note)
	}
}
