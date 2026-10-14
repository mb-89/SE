// Internal test package: package main cannot be imported.
package main

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/guidance"
	"github.com/mb-89/SE/src/internal/issues"
)

func TestOverhaulNewCreatesTheOverhaulAndFires(t *testing.T) {
	calls := recordedIssues(t)
	code, out, errs := se(t, "overhaul", "new", "--repo", "o/r")
	if code != 0 || !strings.Contains(out, "Created the overhaul #10") || !strings.Contains(out, "closes it") || !strings.HasSuffix(out, firedOnce+"\n") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	made := (*calls)[len(*calls)-1]
	for _, want := range []string{"It is the first overhaul.", "<!-- se:overhaul attended -->", "Skills: overhaul " + guidance.Mark, "<!-- se:new -->"} {
		if !strings.Contains(made[6], want) {
			t.Errorf("the body lacks %q: %s", want, made[6])
		}
	}
	if made[len(made)-4] != "labels[]=se" || made[len(made)-2] != "labels[]=se-overhaul" {
		t.Fatalf("%q", made)
	}
	if code, out, _ = se(t, "overhaul", "new", "--unattended", "--repo", "o/r"); code != 0 || !strings.Contains((*calls)[len(*calls)-1][6], "<!-- se:overhaul unattended -->") {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestTakingAnOverhaulHandsOverTheSkillItsBodyNames(t *testing.T) {
	cad := issues.Cadence{Kind: "overhaul", Every: 5, Closed: 5}
	h := handed{Text: "the overhaul skill, in full"}
	r, err := issueReply(false, issues.Issue{Number: 30, Title: "SE overhaul", Overhaul: true}, true, "issue-30", "", h, cad)
	if err != nil || !strings.HasPrefix(r.Text, "Started the unattended overhaul #30 SE overhaul, as 5 retros closed since the last one (the cadence is 5)") ||
		!strings.HasSuffix(r.Text, "\n\nthe overhaul skill, in full") || strings.Contains(r.Text, "se-overhaul") {
		t.Fatalf("%q %v", r.Text, err)
	}
}
