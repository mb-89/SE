// Internal test package: package main cannot be imported.
package main

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/issues"
)

func TestOverhaulNewCreatesTheOverhaulAndFires(t *testing.T) {
	gh := recordedIssues(t)
	code, out, errs := se(t, "overhaul", "new", "--repo", "o/r")
	if code != 0 || !strings.Contains(out, "Created the overhaul #10") || !strings.Contains(out, "closes it") || !strings.HasSuffix(out, firedOnce+"\n") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	made := issueOf(t, gh, 10)
	for _, want := range []string{"It is the first overhaul.", "<!-- se:overhaul attended -->", "<!-- se:new -->"} {
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

func TestTakingAnOverhaulHandsItToTheOverhaulSkill(t *testing.T) {
	cad := issues.Cadence{Kind: "overhaul", Every: 5, Closed: 5}
	r, err := issueReply(false, issues.Issue{Number: 30, Title: "SE overhaul", Overhaul: true}, true, "issue-30", "", cad)
	if err != nil || !strings.HasPrefix(r.Text, "Started the unattended overhaul #30 SE overhaul, as 5 retros closed since the last one (the cadence is 5)") ||
		!strings.Contains(r.Text, "#30 is an overhaul (se-overhaul): follow the overhaul skill, src/plugin/skills/overhaul/SKILL.md, from se overhaul read 30") {
		t.Fatalf("%q %v", r.Text, err)
	}
}
