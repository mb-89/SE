// Internal test package: package main cannot be imported.
package main

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/guidance"
	"github.com/mb-89/SE/src/internal/issues"
	"github.com/mb-89/SE/src/modules/io/disk"
	"github.com/mb-89/SE/src/modules/io/github"
	sehttp "github.com/mb-89/SE/src/modules/io/http"
)

// skillTexts are the two skills the tests hand over; neither is a role an agent holds.
var skillTexts = map[string]string{"briefing": "Take the next issue and land it.\n", "triage": "Collect the window and judge it.\n"}

// inlineOff switches the hand-over's inline switch off for the test.
func inlineOff(t *testing.T) {
	t.Helper()
	worldOf(t).Guided = func() (guidance.Settings, error) { return guidance.Settings{Inline: false, Principles: true}, nil }
}

func TestATakeHandsOverEverySkillItsIssueNamesInFull(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	// #3 names two skills in its marked line.
	if _, err := gh.Send("PATCH", "repos/o/r/issues/3", github.Field{Name: "body", Value: guidance.With("do it", []string{"briefing", "triage"})}); err != nil {
		t.Fatal(err)
	}
	ws := skillsCheckout(t)
	code, out, errs := se(t, "issue", "pull", "--take", "--repo", "o/r", "--workspace", ws)
	if code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	for _, want := range []string{"Take the next issue and land it.", "Collect the window and judge it.", `<skill name="triage" path="src/plugin/skills/triage/SKILL.md">`} {
		if !strings.Contains(out, want) {
			t.Errorf("the take does not hand over %q:\n%s", want, out)
		}
	}
	// With the inline switch off, the hand-over names them only.
	inlineOff(t)
	c := &Call{Workspace: ws, World: *worldOf(t)}
	h := c.handOver(issues.Issue{Number: 3, Body: guidance.With("do it", []string{"briefing", "triage"})})
	if len(h.Skills) != 2 || strings.Contains(h.Text, "Take the next issue") || !strings.Contains(h.Text, "- triage: src/plugin/skills/triage/SKILL.md") {
		t.Fatalf("%+v", h)
	}
}

// skillsCheckout answers a clone of a fresh origin whose main holds skillTexts.
func skillsCheckout(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	origin, ws := filepath.Join(root, "origin.git"), filepath.Join(root, "ws")
	gitIn := func(dir string, args ...string) {
		t.Helper()
		if out, err := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	gitIn(root, "init", "-q", "--bare", "-b", "main", origin)
	gitIn(root, "clone", "-q", origin, ws)
	gitIn(ws, "checkout", "-q", "-b", "main")
	for name, text := range skillTexts {
		path := filepath.Join(ws, guidance.PathOf(name))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	gitIn(ws, "add", ".")
	gitIn(ws, "commit", "-q", "-m", "skills")
	gitIn(ws, "push", "-q", "origin", "main")
	return ws
}

// TestATakeOfAnIssueWhoseSkillsLineNamesARoleHandsOverNoDeletedSkill takes an
// open issue whose skills line, written before the roles moved into the
// plugin's agents, names overhaul and retro: no skill file holds them any
// more, and the take neither reports them missing nor hands them over, while
// a real skill on the same line still goes over.
func TestATakeOfAnIssueWhoseSkillsLineNamesARoleHandsOverNoDeletedSkill(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	if _, err := gh.Send("PATCH", "repos/o/r/issues/3", github.Field{Name: "body", Value: "do it\n\nSkills: overhaul, triage, retro " + guidance.Mark}); err != nil {
		t.Fatal(err)
	}
	ws := skillsCheckout(t)
	code, out, errs := se(t, "issue", "pull", "--take", "--json", "--repo", "o/r", "--workspace", ws)
	if code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	var took struct {
		Agent    string
		Skills   []guidance.Skill
		Guidance string
	}
	if err := json.Unmarshal([]byte(out), &took); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(took.Guidance, "not handed over") || len(took.Skills) != 1 || took.Skills[0].Name != "triage" || took.Agent == "" {
		t.Fatalf("the take: %+v", took)
	}
	// A line naming roles alone hands over nothing, and says nothing.
	c := &Call{Workspace: ws, World: *worldOf(t)}
	if h := c.handOverSkills(issues.Issue{Number: 3, Body: guidance.With("do it", []string{"overhaul", "coordination"})}); h.Text != "" || len(h.Skills) != 0 {
		t.Fatalf("%+v", h)
	}
}

func TestIssueNewNamesTheSkillsAndRefusesOneThatDoesNotExist(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	ws := t.TempDir()
	if err := os.MkdirAll(filepath.Join(ws, "src/plugin/skills/triage"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(ws, guidance.PathOf("triage")), []byte("w"), 0o644); err != nil {
		t.Fatal(err)
	}
	if code, _, errs := se(t, "issue", "new", "--title", "t", "--body", "b", "--blocked-by", "none", "--skills", "triage,nope", "--repo", "o/r", "--workspace", ws); code == 0 || !strings.Contains(errs, "no skill nope") || len(gh.Writes()) != 0 {
		t.Fatalf("exit %d, %q, wrote %q", code, errs, gh.Writes())
	}
	if code, out, errs := se(t, "issue", "new", "--title", "t", "--body", "b", "--blocked-by", "none", "--skills", "triage,overhaul", "--repo", "o/r", "--workspace", ws); code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	var made struct{ Body string }
	// The first goes into a new misc manifest, #10.
	if err := json.Unmarshal([]byte(issueOf(t, gh, 11)), &made); err != nil || !strings.Contains(made.Body, "b\n\nSkills: triage "+guidance.Mark+"\n\n"+issues.NewMark) {
		t.Fatalf("%q %v", made.Body, err)
	}
	// A role an agent holds is no skill: it writes no skills line.
	if code, out, errs := se(t, "issue", "new", "--title", "u", "--body", "b", "--blocked-by", "none", "--skills", "retro", "--repo", "o/r", "--workspace", ws); code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	if err := json.Unmarshal([]byte(issueOf(t, gh, 12)), &made); err != nil || strings.Contains(made.Body, guidance.Mark) {
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
			Clock: worldOf(t).Clock, Net: net, Modules: modules(daemon.Paths{Workspace: ws, Disk: d}, worldOf(t).Clock, nil, nil),
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
	h := c.handOver(issues.Issue{Number: 3, Body: guidance.With("do it", []string{"briefing", "triage"})})
	if len(h.Skills) != 2 || !strings.Contains(h.Text, "Take the next issue") || !strings.Contains(h.Text, "Collect the window") {
		t.Fatalf("%+v", h)
	}
	rows := handOverRows(t, d, ws)
	if len(rows) != 1 || rows[0].Again || len(rows[0].Skills) != 2 || rows[0].Skills[0].Name != "briefing" || rows[0].Skills[0].Hash != h.Skills[0].Hash {
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
