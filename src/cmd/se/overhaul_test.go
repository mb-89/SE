// Internal test package: package main cannot be imported.
package main

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/issues"
)

func TestOverhaulNewCreatesTheOverhaulAndFires(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	code, out, errs := se(t, "overhaul", "new", "--repo", "o/r")
	if code != 0 || !strings.Contains(out, "Created the overhaul #10") || !strings.Contains(out, "closes it") || !strings.HasSuffix(out, firedOnce+"\n") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	made := issueOf(t, gh, 10)
	for _, want := range []string{"It is the first overhaul.", "<!-- se:overhaul attended -->", "starts its agent, se:overhaul", "<!-- se:new -->"} {
		if !strings.Contains(made, want) {
			t.Errorf("the body lacks %q: %s", want, made)
		}
	}
	if !strings.Contains(made, `"labels":[{"name":"se"},{"name":"se-overhaul"}]`) {
		t.Fatal(made)
	}
	if code, out, _ = se(t, "overhaul", "new", "--unattended", "--repo", "o/r"); code != 0 || !strings.Contains(issueOf(t, gh, 11), "<!-- se:overhaul unattended -->") {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestTakingAnOverhaulHandsOverTheSkillItsBodyNames(t *testing.T) {
	t.Parallel()
	cad := issues.Cadence{Kind: "overhaul", Every: 5, Closed: 5}
	h := handed{Text: "the overhaul skill, in full"}
	r, err := issueReply(false, issues.Issue{Number: 30, Title: "SE overhaul", Overhaul: true}, true, "issue-30", "", "", h, cad)
	if err != nil || !strings.HasPrefix(r.Text, "Started the unattended overhaul #30 SE overhaul, as 5 retros closed since the last one (the cadence is 5)") ||
		!strings.HasSuffix(r.Text, "\n\nthe overhaul skill, in full") || strings.Contains(r.Text, "se-overhaul") {
		t.Fatalf("%q %v", r.Text, err)
	}
}
