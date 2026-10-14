// Internal test package: the trace is printed by package main, which cannot be imported.
package main

import (
	"regexp"
	"strings"
	"testing"
)

// se --trace prints, once the command is done, each GitHub request it made:
// its start and duration from the run's start, its status, method and path,
// by start. What the command prints is left as it is.
func TestTracePrintsEachGitHubRequest(t *testing.T) {
	t.Parallel()
	recordedIssues(t)
	_, plain, _ := se(t, "issue", "pull", "--repo", "o/r", "--workspace", t.TempDir())
	code, out, errs := se(t, "--trace", "issue", "pull", "--repo", "o/r", "--workspace", t.TempDir())
	if code != 0 || out != plain {
		t.Fatalf("exit %d, %q, want %q", code, out, plain)
	}
	lines := strings.Split(strings.TrimSuffix(errs, "\n"), "\n")
	head := regexp.MustCompile(`^se --trace: 0\.00s, (\d+) GitHub requests$`).FindStringSubmatch(lines[0])
	if head == nil || head[1] == "0" || len(lines) < 2 {
		t.Fatalf("the trace: %q", errs)
	}
	line := regexp.MustCompile(`^ +0\.00  0\.00 200 (GET|LIST) repos/o/r/\S+$`)
	issues := false
	for _, l := range lines[1:] {
		if !line.MatchString(l) {
			t.Errorf("a request is traced as %q", l)
		}
		issues = issues || strings.Contains(l, " repos/o/r/issues?")
	}
	if !issues {
		t.Errorf("the issue list is not traced: %q", errs)
	}
	if _, _, errs := se(t, "issue", "pull", "--repo", "o/r", "--workspace", t.TempDir()); errs != "" {
		t.Errorf("without --trace, stderr has %q", errs)
	}
}
