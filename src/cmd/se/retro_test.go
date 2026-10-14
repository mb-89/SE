// Internal test package: package main cannot be imported.
package main

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/issues"
)

func TestRetroNewAsksForFieldFeedbackOrNone(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	for _, args := range [][]string{
		{"retro", "new", "--repo", "o/r"},
		{"retro", "new", "--no-field", "--unattended", "--repo", "o/r"},
		{"retro", "new", "--field", " ", "--repo", "o/r"},
	} {
		if code, _, errs := se(t, args...); code == 0 || !strings.Contains(errs, "--field") {
			t.Errorf("%q: exit %d, %q", args, code, errs)
		}
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused retro new wrote %q", w)
	}
}

func TestRetroNewCreatesTheRetroAndFires(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	code, out, errs := se(t, "retro", "new", "--field", "the boxes were slow", "--repo", "o/r")
	if code != 0 || !strings.Contains(out, "Created the retro #10") || !strings.Contains(out, "over the whole history") || !strings.HasSuffix(out, firedOnce+"\n") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	// The closed retros are listed first; the recorded repository has none.
	made := issueOf(t, gh, 10)
	for _, want := range []string{"## Field feedback\\nthe boxes were slow", "<!-- se:retro attended -->", "starts its agent, se:retro", "<!-- se:new -->"} {
		if !strings.Contains(made, want) {
			t.Errorf("the body lacks %q: %s", want, made)
		}
	}
	if !strings.Contains(made, `"labels":[{"name":"se"},{"name":"se-retro"}]`) {
		t.Fatal(made)
	}
}

func TestARetroIsNoLongerDispatchedByItsLabel(t *testing.T) {
	t.Parallel()
	r, err := issueReply(false, issues.Issue{Number: 30, Title: "SE retro", Retro: true}, true, "issue-30", "", "", handed{})
	if err != nil || strings.Contains(r.Text, "se-retro") || strings.Contains(r.Text, "SKILL.md") {
		t.Fatalf("%q %v", r.Text, err)
	}
}
