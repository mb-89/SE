// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"reflect"
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
	hubAt(t, answers)
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

func TestFleetPruneDeletesOnlyWithApply(t *testing.T) {
	answers := map[string]string{
		"repos/o/r/pulls?state=open&per_page=100":   `[]`,
		"repos/o/r/git/matching-refs/heads/issue-":  `[{"ref":"refs/heads/issue-19","object":{"sha":"c19"}}]`,
		"repos/o/r/git/matching-refs/heads/claude/": `[]`,
		"repos/o/r/issues/19":                       `{"number":19,"state":"closed"}`,
	}
	gh := hubAt(t, answers)
	if code, out, errs := se(t, "fleet", "prune", "--repo", "o/r"); code != 0 || out != "stray issue-19 at c19: #19 is closed and issue-19 has no open PR\n" || len(gh.Writes()) != 0 {
		t.Fatalf("exit %d, %q %q, writes %q", code, out, errs, gh.Writes())
	}
	if code, out, errs := se(t, "fleet", "prune", "--apply", "--repo", "o/r"); code != 0 || out != "deleted issue-19 at c19: #19 is closed and issue-19 has no open PR\n" ||
		!reflect.DeepEqual(gh.Writes(), []string{"DELETE repos/o/r/git/refs/heads/issue-19"}) {
		t.Fatalf("exit %d, %q %q, writes %q", code, out, errs, gh.Writes())
	}
	// The branch is gone, so a second prune finds nothing.
	if code, out, _ := se(t, "fleet", "prune", "--apply", "--repo", "o/r"); code != 0 || out != "no stray branches\n" {
		t.Fatalf("exit %d, %q", code, out)
	}
}
