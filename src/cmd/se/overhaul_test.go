// Internal test package: package main cannot be imported.
package main

import (
	"fmt"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/proc"
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

func TestOverhaulReadHandsTheCodeFactsOnPrinciples2And3(t *testing.T) {
	hubAt(t, map[string]string{
		"repos/o/r/issues/31":                                           `{"number":31,"state":"open","body":"<!-- se:overhaul unattended -->","labels":[{"name":"se-overhaul"}]}`,
		"repos/o/r/issues/31/comments?per_page=100":                     `[]`,
		"repos/o/r/issues?labels=se-retro&state=closed&per_page=100":    `[]`,
		"repos/o/r/issues?labels=se-overhaul&state=closed&per_page=100": `[{"number":15,"state":"closed","closed_at":"2026-09-01T00:00:00Z"}]`,
		"repos/o/r/issues/15/comments?per_page=100":                     `[]`,
	})
	d := onFake(t)
	put(t, d, "/ws/spec/principles.md", "1. **Single point of truth.**\n   Checked by: overhaul, by judgment.\n")
	put(t, d, "/ws/src/a/a.go", "package a\n\nfunc Used() {}\n\nfunc Forgotten() {}\n\ntype T struct{}\n\nfunc (T) String() string { return \"\" }\n")
	put(t, d, "/ws/src/a/a_test.go", "package a_test\n\nfunc use() { a.Used() }\n")
	// One PR before the previous overhaul closed, two after; spec/old.md was
	// last touched by the first.
	m := proc.NewFake()
	m.Install("git", func(c proc.Cmd) int {
		switch strings.Join(c.Args, " ") {
		case "log --no-renames --format=%x1e%at%x1f%s --name-only HEAD":
			fmt.Fprintf(c.Stdout, "%s", "\x1e1791000000\x1fWide (#40)\n\nsrc/a/a.go\nsrc/a/a_test.go\nREADME.md\n"+
				"\x1e1790000000\x1fNarrow (#30)\n\nsrc/a/a.go\n"+
				"\x1e1780000000\x1fBefore (#20)\n\nspec/old.md\nsrc/a/a.go\nsrc/a/a_test.go\nREADME.md\nspec/principles.md\n")
		case "ls-files":
			fmt.Fprintf(c.Stdout, "%s", "README.md\nspec/old.md\nspec/principles.md\nsrc/a/a.go\nsrc/a/a_test.go\n")
		default:
			return 1
		}
		return 0
	})
	old := machine
	machine = m
	t.Cleanup(func() { machine = old })
	if code, out, errs := se(t, "overhaul", "read", "31", "--repo", "o/r", "--workspace", "/ws"); code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	data, err := d.ReadFile("/overhaul-31.md")
	if err != nil {
		t.Fatal(err)
	}
	draft := string(data)
	for _, want := range []string{
		"The PRs merged since the previous overhaul closed, 2026-09-01, that touched the most files:",
		"| #40 | Wide | 3 |\n| #30 | Narrow | 1 |\n\n",
		"- `Forgotten` at src/a/a.go:5\n\n",
		"| spec/old.md | 2026-05-28 |\n| spec/principles.md | 2026-05-28 |\n",
	} {
		if !strings.Contains(draft, want) {
			t.Errorf("the draft lacks %q:\n%s", want, draft)
		}
	}
	if strings.Contains(draft, "#20 | Before") || strings.Contains(draft, "`Used`") || strings.Contains(draft, "`String`") {
		t.Fatalf("the draft lists too much:\n%s", draft)
	}
	r, _, err := issues.ParseOverhaul(draft)
	if err != nil || len(r.Code.Widest) != 2 || len(r.Code.Unreached) != 1 || r.Code.Untouched[0].Path != "spec/old.md" {
		t.Fatalf("the block: %+v %v", r.Code, err)
	}
}
