// Internal test package: package main cannot be imported.
package main

import (
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/guidance"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/issues"
)

// skillTexts are the two skills the tests hand over.
var skillTexts = map[string]string{"work": "Take the next issue and land it.\n", "retro": "Collect the window and judge it.\n"}

// inlineOff switches the hand-over's inline switch off for the test.
func inlineOff(t *testing.T) {
	t.Helper()
	worldOf(t).Guided = func() (guidance.Settings, error) { return guidance.Settings{Inline: false, Principles: true}, nil }
}

func TestATakeHandsOverEverySkillItsIssueNamesInFull(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	// #3 names two skills in its marked line.
	if _, err := gh.Send("PATCH", "repos/o/r/issues/3", github.Field{Name: "body", Value: guidance.With("do it", []string{"work", "retro"})}); err != nil {
		t.Fatal(err)
	}
	ws := clone(t)
	for name, text := range skillTexts {
		put(t, onFake(t), filepath.Join(ws, guidance.PathOf(name)), text)
	}
	git(t, ws, "add", ".")
	git(t, ws, "commit", "-q", "-m", "skills")
	git(t, ws, "push", "-q", "origin", "main")
	code, out, errs := se(t, "issue", "pull", "--take", "--repo", "o/r", "--workspace", ws)
	if code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	for _, want := range []string{"Take the next issue and land it.", "Collect the window and judge it.", `<skill name="retro" path="src/plugin/skills/retro/SKILL.md">`} {
		if !strings.Contains(out, want) {
			t.Errorf("the take does not hand over %q:\n%s", want, out)
		}
	}
	// With the inline switch off, the hand-over names them only.
	inlineOff(t)
	c := &Call{Workspace: ws, World: *worldOf(t)}
	h := c.handOver(issues.Issue{Number: 3, Body: guidance.With("do it", []string{"work", "retro"})})
	if len(h.Skills) != 2 || strings.Contains(h.Text, "Take the next issue") || !strings.Contains(h.Text, "- retro: src/plugin/skills/retro/SKILL.md") {
		t.Fatalf("%+v", h)
	}
}

func TestIssueNewNamesTheSkillsAndRefusesOneThatDoesNotExist(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	ws := filepath.FromSlash("/ws")
	put(t, onFake(t), filepath.Join(ws, guidance.PathOf("work")), "w")
	if code, _, errs := se(t, "issue", "new", "--title", "t", "--body", "b", "--blocked-by", "none", "--skills", "work,nope", "--repo", "o/r", "--workspace", ws); code == 0 || !strings.Contains(errs, "no skill nope") || len(gh.Writes()) != 0 {
		t.Fatalf("exit %d, %q, wrote %q", code, errs, gh.Writes())
	}
	if code, out, errs := se(t, "issue", "new", "--title", "t", "--body", "b", "--blocked-by", "none", "--skills", "work", "--repo", "o/r", "--workspace", ws); code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	var made struct{ Body string }
	if err := json.Unmarshal([]byte(issueOf(t, gh, 10)), &made); err != nil || !strings.Contains(made.Body, "b\n\nSkills: work "+guidance.Mark+"\n\n"+issues.NewMark) {
		t.Fatalf("%q %v", made.Body, err)
	}
}

// TestTheSessionLogRecordsTheHandOverAndACompactionHandsItAgain serves a
// daemon on a fake network and disk: a hand-over is a row of the session's
// log, by name and hash, and se guidance, which the plugin runs after a
// compaction, answers the principles and the skills that row names.
func TestTheSessionLogRecordsTheHandOverAndACompactionHandsItAgain(t *testing.T) {
	t.Parallel()
	net := sehttp.NewFake()
	worldOf(t).Net = net
	setenv(t, issues.SessionVar, "s1")
	d, ws := onFake(t), "/ws"
	put(t, d, filepath.Join(ws, guidance.Principles), "1. Mechanize first.\n")
	for name, text := range skillTexts {
		put(t, d, filepath.Join(ws, guidance.PathOf(name)), text)
	}
	ctx, stop := context.WithCancel(context.Background())
	done := make(chan error, 1)
	ready := make(chan daemon.Endpoint, 1)
	go func() {
		done <- daemon.Serve(ctx, daemon.Paths{Workspace: ws, Disk: d}, daemon.Options{
			Clock: worldOf(t).Clock, Net: net, Modules: modules(daemon.Paths{Workspace: ws, Disk: d}, worldOf(t).Clock),
			Ready: func(ep daemon.Endpoint) { ready <- ep },
		})
	}()
	select {
	case <-ready:
	case err := <-done:
		t.Fatalf("the daemon did not start: %v", err)
	}
	t.Cleanup(func() {
		stop()
		<-done
	})
	c := &Call{Workspace: ws, World: *worldOf(t)}
	h := c.handOver(issues.Issue{Number: 3, Body: guidance.With("do it", []string{"work", "retro"})})
	if len(h.Skills) != 2 || !strings.Contains(h.Text, "Take the next issue") || !strings.Contains(h.Text, "Collect the window") {
		t.Fatalf("%+v", h)
	}
	rows := handOverRows(t, d, ws)
	if len(rows) != 1 || rows[0].Again || len(rows[0].Skills) != 2 || rows[0].Skills[0].Name != "work" || rows[0].Skills[0].Hash != h.Skills[0].Hash {
		t.Fatalf("the log: %+v", rows)
	}
	code, out, errs := se(t, "guidance", "--session-id", "s1", "--workspace", ws)
	for _, want := range []string{"1. Mechanize first.", "Take the next issue and land it.", "Collect the window and judge it."} {
		if code != 0 || !strings.Contains(out, want) {
			t.Errorf("exit %d: se guidance lacks %q: %q %q", code, want, out, errs)
		}
	}
	if rows = handOverRows(t, d, ws); len(rows) != 2 || !rows[1].Again {
		t.Fatalf("the hand-again is no row of the log: %+v", rows)
	}
	// A session no take handed anything to gets the principles alone.
	if code, out, _ = se(t, "guidance", "--session-id", "s2", "--workspace", ws); code != 0 || out != "SE's design principles (spec/principles.md), which every change is measured against:\n\n1. Mechanize first.\n" {
		t.Fatalf("exit %d, %q", code, out)
	}
}

// handOverRows answers the hand-overs session s1's log records.
func handOverRows(t *testing.T, d disk.Disk, ws string) []handOverRow {
	t.Helper()
	data, err := d.ReadFile(filepath.Join(ws, ".se/.runtime/logs/s1.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	var rows []handOverRow
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		var row struct {
			Event string
			E     handOverRow
		}
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			t.Fatal(err)
		}
		if row.Event == guidance.Event {
			rows = append(rows, row.E)
		}
	}
	return rows
}
