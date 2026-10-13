package main

import (
	"encoding/json"
	"fmt"
	"testing"
)

// recordedFleet answers the fleet commands' gh calls for o/r: #3 is ready,
// nothing is claimed, and nothing is broken.
func recordedFleet(t *testing.T) {
	t.Helper()
	answers := map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100":      `[{"number":3,"title":"three","state":"open","html_url":"u3"}]`,
		"repos/o/r/git/matching-refs/heads/issue-":                `[]`,
		"repos/o/r/issues/3/dependencies/blocked_by?per_page=100": `[]`,
		"repos/o/r/pulls?base=main&state=open&per_page=100":       `[]`,
	}
	old := gh
	gh = func(args ...string) ([]byte, error) {
		a, ok := answers[args[len(args)-1]]
		if !ok {
			return nil, fmt.Errorf("not recorded: %v", args)
		}
		return []byte(a), nil
	}
	t.Cleanup(func() { gh = old })
}

func TestAHealthyFleetSaysSo(t *testing.T) {
	recordedFleet(t)
	for _, cmd := range []string{"check", "fix"} {
		if code, out, errs := se(t, "fleet", cmd, "--repo", "o/r"); code != 0 || out != "healthy\n" {
			t.Fatalf("fleet %s: exit %d, %q %q", cmd, code, out, errs)
		}
	}
	code, out, _ := se(t, "fleet", "check", "--json", "--repo", "o/r")
	var answer struct {
		Healthy  bool
		Findings []any
	}
	if err := json.Unmarshal([]byte(out), &answer); code != 0 || err != nil || !answer.Healthy || answer.Findings == nil || len(answer.Findings) != 0 {
		t.Fatalf("exit %d, %q %v", code, out, err)
	}
	if r := session(t, "fleet", "check", "--repo", "o/r"); r.Text != "healthy" {
		t.Fatalf("%+v", r)
	}
}
