// Internal test package: package main cannot be imported.
package main

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/guidance"
	"github.com/mb-89/SE/src/internal/issues"
)

func TestRetroNewAsksForFieldFeedbackOrNone(t *testing.T) {
	calls := recordedIssues(t)
	for _, args := range [][]string{
		{"retro", "new", "--repo", "o/r"},
		{"retro", "new", "--no-field", "--unattended", "--repo", "o/r"},
		{"retro", "new", "--field", " ", "--repo", "o/r"},
	} {
		if code, _, errs := se(t, args...); code == 0 || !strings.Contains(errs, "--field") {
			t.Errorf("%q: exit %d, %q", args, code, errs)
		}
	}
	if len(*calls) != 0 {
		t.Fatalf("a refused retro new called gh: %q", *calls)
	}
}

func TestRetroNewCreatesTheRetroAndFires(t *testing.T) {
	calls := recordedIssues(t)
	code, out, errs := se(t, "retro", "new", "--field", "the boxes were slow", "--repo", "o/r")
	if code != 0 || !strings.Contains(out, "Created the retro #10") || !strings.Contains(out, "over the whole history") || !strings.HasSuffix(out, firedOnce+"\n") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	// The closed retros are listed first; the recorded repository has none.
	made := (*calls)[len(*calls)-1]
	body := made[6]
	for _, want := range []string{"## Field feedback\nthe boxes were slow", "<!-- se:retro attended -->", "Skills: retro " + guidance.Mark, "<!-- se:new -->"} {
		if !strings.Contains(body, want) {
			t.Errorf("the body lacks %q: %s", want, body)
		}
	}
	if made[len(made)-4] != "labels[]=se" || made[len(made)-2] != "labels[]=se-retro" {
		t.Fatalf("%q", made)
	}
}

func TestARetroIsNoLongerDispatchedByItsLabel(t *testing.T) {
	r, err := issueReply(false, issues.Issue{Number: 30, Title: "SE retro", Retro: true}, true, "issue-30", "", handed{})
	if err != nil || strings.Contains(r.Text, "se-retro") || strings.Contains(r.Text, "SKILL.md") {
		t.Fatalf("%q %v", r.Text, err)
	}
}
