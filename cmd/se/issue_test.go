package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

// recordedIssues answers the issue commands' gh calls for o/r: #1 claimed,
// #2 blocked by #1, #3 ready.
func recordedIssues(t *testing.T) {
	t.Helper()
	answers := map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100": `[
			{"number":3,"title":"three","body":"do it","state":"open","html_url":"u3","issue_dependencies_summary":{"total_blocked_by":0}},
			{"number":2,"title":"two","body":"","state":"open","html_url":"u2","issue_dependencies_summary":{"total_blocked_by":1}},
			{"number":1,"title":"one","body":"","state":"open","html_url":"u1","issue_dependencies_summary":{"total_blocked_by":0}}]`,
		"repos/o/r/git/matching-refs/heads/issue-":                `[{"ref":"refs/heads/issue-1"}]`,
		"repos/o/r/issues/2/dependencies/blocked_by?per_page=100": `[{"number":1,"state":"open"}]`,
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

func TestIssueNextNamesTheNextReadyIssue(t *testing.T) {
	recordedIssues(t)
	code, out, errs := se(t, "issue", "next", "--repo", "o/r")
	if code != 0 || out != "#3 three\nu3\n\ndo it\n" {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, out, _ = se(t, "issue", "next", "--json", "--repo", "o/r")
	var answer struct {
		Ready bool
		Issue struct{ Number int }
	}
	if err := json.Unmarshal([]byte(out), &answer); code != 0 || err != nil || !answer.Ready || answer.Issue.Number != 3 {
		t.Fatalf("exit %d, %q %v", code, out, err)
	}
}

func TestIssueNextIsOfferedInASession(t *testing.T) {
	recordedIssues(t)
	if r := session(t, "issue", "next", "--repo", "o/r"); !strings.HasPrefix(r.Text, "#3 three") {
		t.Fatalf("%+v", r)
	}
	if r := session(t, "issue"); r.Text != "/se issue takes a word: next." {
		t.Fatalf("%+v", r)
	}
}

func TestIssueWithoutASubWordNamesThem(t *testing.T) {
	code, _, errs := se(t, "issue")
	if code != 2 || strings.TrimSpace(errs) != "se issue takes a word: next." {
		t.Fatalf("exit %d, %q", code, errs)
	}
}

func TestThereIsNoTakeCommand(t *testing.T) {
	if _, ok := commands["issue take"]; ok {
		t.Fatal("take is a flag of issue next, not a command")
	}
	if code, _, errs := se(t, "issue", "take"); code != 2 || !strings.Contains(errs, "se issue takes a word: next.") {
		t.Fatalf("exit %d, %q", code, errs)
	}
}

func TestIssueNextTakeRefusesABadNumber(t *testing.T) {
	recordedIssues(t)
	for _, args := range [][]string{{"3"}, {"--take", "x"}, {"--take", "3", "4"}, {"--take=3", "4"}, {"--take", "0"}} {
		code, _, errs := se(t, append([]string{"issue", "next", "--repo", "o/r"}, args...)...)
		if code != 1 || !strings.Contains(errs, "issue number") {
			t.Errorf("%v: exit %d, %q", args, code, errs)
		}
	}
	if code, _, errs := se(t, "issue", "next", "--take=x", "--repo", "o/r"); code != 1 || !strings.Contains(errs, `--take takes an issue number, not "x"`) {
		t.Errorf("exit %d, %q", code, errs)
	}
	// Each spelling of --take N reaches the claim of issue 2, which is blocked.
	for _, args := range [][]string{{"--take", "2"}, {"--take=2"}, {"--take", "#2"}, {"--take", "--json", "2"}} {
		code, _, errs := se(t, append([]string{"issue", "next", "--repo", "o/r", "--workspace", t.TempDir()}, args...)...)
		if code != 1 || !strings.Contains(errs, "#2 is not ready: blocked by #1") {
			t.Errorf("%v: exit %d, %q", args, code, errs)
		}
	}
}
