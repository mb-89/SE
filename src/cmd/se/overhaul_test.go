// Internal test package: package main cannot be imported.
package main

import (
	"fmt"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
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
	r, err := issueReply(false, false, issues.Issue{Number: 30, Title: "SE overhaul", Overhaul: true}, true, "issue-30", "", "", h, cad)
	if err != nil || !strings.HasPrefix(r.Text, "Started the unattended overhaul #30 SE overhaul, as 5 retros closed since the last one (the cadence is 5)") ||
		!strings.HasSuffix(r.Text, "\n\nthe overhaul skill, in full") || strings.Contains(r.Text, "se-overhaul") {
		t.Fatalf("%q %v", r.Text, err)
	}
}

func TestOverhaulReadWritesTheCodeFactsIntoTheDraft(t *testing.T) {
	t.Parallel()
	hubAt(t, map[string]string{
		"repos/o/r/issues/31": `{"number":31,"state":"open","body":"<!-- se:overhaul attended -->","labels":[{"name":"se-overhaul"}]}`,
	})
	d := disk.NewFake()
	for path, text := range map[string]string{
		"/ws/spec/principles.md":    "# Design principles\n\n1. **Mechanize first.**\n   Checked by: retro, mechanically.\n",
		"/ws/src/go.mod":            "module example.com/ws\n",
		"/ws/src/cmd/app/main.go":   "package main\n\nfunc main() {}\n",
		"/ws/src/internal/x/x.go":   "package x\n\n// Gone is kept for old reports.\nfunc Gone() {}\n",
		"/ws/src/scripts/fix.sh":    "#!/bin/sh\n# Why: a one-off.\n",
		"/ws/src/scripts/README.md": "# Scripts\n",
	} {
		if err := d.MkdirAll(filepath.Dir(path)); err != nil {
			t.Fatal(err)
		}
		if err := d.WriteFile(path, []byte(text)); err != nil {
			t.Fatal(err)
		}
	}
	m := proc.NewFake()
	m.Install("deadcode", func(c proc.Cmd) int { fmt.Fprintln(c.Stdout, "internal/x/x.go:4:6: unreachable func: Gone"); return 0 })
	m.Install("git", func(proc.Cmd) int { return 0 })
	w := worldOf(t)
	w.Disk, w.Proc = d, m
	code, out, errs := se(t, "overhaul", "read", "31", "--repo", "o/r", "--workspace", "/ws", "--out", "/draft.md")
	if code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	draft, err := d.ReadFile("/draft.md")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"## Pruning and code shape",
		"- src/internal/x/x.go:4: Gone",
		"- src/internal/x/x.go:3: Gone is kept for old reports.",
		"`se overhaul read`",
		"- src/scripts/fix.sh (not read by a retro yet, added at no known time): a one-off",
	} {
		if !strings.Contains(string(draft), want) {
			t.Errorf("the draft lacks %q:\n%s", want, draft)
		}
	}
	if _, _, err := issues.ParseOverhaul(string(draft)); err != nil {
		t.Fatal(err)
	}
}
