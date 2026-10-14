// Internal test package: it reads the fake GitHub's pulls and the landings back.
package issues

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/modules/io/clock"
	"github.com/mb-89/SE/src/modules/io/disk"
)

// branchCreated is GitHub's record that issue n's branch was created at.
func branchCreated(n int, at time.Time) (string, string) {
	return fmt.Sprintf("repos/o/r/activity?ref=refs/heads/issue-%d&activity_type=branch_creation&per_page=100", n), pushed(at.Format(time.RFC3339))
}

// pullsIn reads every PR the fake GitHub holds.
func pullsIn(t *testing.T, s Source) []pull {
	t.Helper()
	got, err := api[pull](s, "repos/o/r/pulls?state=all&per_page=100", true)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

// A manifest with three leaves lands once: each leaf's landing merges it
// into issue-<manifest> and closes it, with no PR of its own, and the
// manifest lands as one PR.
func TestAManifestOfThreeLeavesLandsAsOnePR(t *testing.T) {
	t.Parallel()
	origin, a, b := boxes(t)
	c := clock.NewFake(landedAt())
	claimed := landedAt().Add(-90 * time.Minute)
	answers := map[string]string{
		listPath:      list(node(1, 3), node(2, 0), node(3, 0), node(4, 0)),
		subsPath(1):   list(node(2, 0), node(3, 0), node(4, 0)),
		refsPath:      `[{"ref":"refs/heads/issue-1"}]`,
		openPullsPath: `[]`,
	}
	for n := 1; n <= 4; n++ {
		path, at := branchCreated(n, claimed)
		answers[path] = at
	}
	gh := recordedAt(t, c, answers)
	s := Source{Git: machine, Repo: repo, GitHub: gh, Clock: c, Disk: disk.NewFake()}
	// The coordinator took #1 at the top: its branch claims the tree.
	if took, ok, err := s.Take(a, 0); err != nil || !ok || took.Number != 1 || !took.Parent {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	run(t, a, "checkout", "-q", "main")
	for n := 2; n <= 4; n++ {
		if took, ok, _, err := s.TakeIn(a, 1, n); err != nil || !ok || took.Number != n {
			t.Fatalf("took %+v %v %v", took, ok, err)
		}
		wt := filepath.Join(filepath.Dir(a), Branch(n))
		run(t, a, "worktree", "add", "-q", "--track", "-b", Branch(n), wt, "origin/"+Branch(n))
		if err := os.WriteFile(filepath.Join(wt, fmt.Sprintf("leaf%d", n)), []byte("work\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		run(t, wt, "add", ".")
		run(t, wt, "commit", "-q", "-m", fmt.Sprintf("work on %d", n))
		l, err := s.Land(wt, "", qs, full, passes)
		if err != nil {
			t.Fatal(err)
		}
		if want := (Landing{Issue: n, Manifest: 1, Into: "issue-1", Closed: true}); l != want {
			t.Fatalf("landed %+v, want %+v", l, want)
		}
		if got := issueAt(t, gh, n); got.State != "closed" || got.StateReason != "completed" {
			t.Fatalf("#%d is %s (%s)", n, got.State, got.StateReason)
		}
		// The landing's facts carry its duration, from the claim, and where it landed.
		posted := commentsAt(t, gh, n)
		back, ok, err := ParseLanding(posted[0].Body)
		if err != nil || !ok || back.Facts.Into != "issue-1" || back.Facts.Minutes != 90 || back.Facts.Commits != 1 {
			t.Fatalf("%+v %v %v", back, ok, err)
		}
		if got := pullsIn(t, s); len(got) != 0 {
			t.Fatalf("a leaf opened a PR: %+v", got)
		}
	}
	// All three are on the manifest's branch, merged, never rebased.
	log := run(t, origin, "log", "--format=%s", "issue-1")
	for n := 2; n <= 4; n++ {
		if !strings.Contains(log, fmt.Sprintf("work on %d", n)) {
			t.Fatalf("issue-1 lacks #%d's work:\n%s", n, log)
		}
	}
	if !labelled(t, gh, 1, ManifestLabel) {
		t.Fatal("#1 is not labelled a manifest")
	}
	// Its leaves done, #1 does not close by itself: it is ready to land.
	tr, err := s.In(1)
	if err != nil || !tr.Land || tr.Closed {
		t.Fatalf("%+v %v", tr, err)
	}
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 1 {
		t.Fatalf("next %+v %v %v", next, ok, err)
	}
	// The coordinator lands it: one PR, Fixes #1, auto-merge on.
	run(t, b, "fetch", "-q", "origin")
	run(t, b, "checkout", "-q", "-b", "issue-1", "--track", "origin/issue-1")
	l, err := s.Land(b, "", qs, full, battered(s.Disk))
	if err != nil || !l.Created || l.Manifest != 0 {
		t.Fatalf("%+v %v", l, err)
	}
	got := pullsIn(t, s)
	if len(got) != 1 || got[0].Number != l.Number {
		t.Fatalf("PRs %+v", got)
	}
	pr := pullOf(t, gh, l.Number)
	if pr["body"] != "Fixes #1" || pr["head"].(map[string]any)["ref"] != "issue-1" || pr["auto_merge"] == nil {
		t.Fatalf("the PR is %+v", pr)
	}
	back, ok, err := ParseLanding(commentsAt(t, gh, 1)[len(commentsAt(t, gh, 1))-1].Body)
	if err != nil || !ok || back.Facts.Minutes != 90 || back.Facts.Into != "" || back.Facts.Commits != 3 {
		t.Fatalf("the manifest's landing %+v %v %v", back, ok, err)
	}
	// With its PR open, it is not offered again.
	seed(t, gh, map[string]string{openPullsPath: fmt.Sprintf(`[{"number":%d,"head":{"ref":"issue-1"},"base":{"ref":"main"}}]`, l.Number)})
	if next, ok, err := s.Next(); err != nil || ok {
		t.Fatalf("next %+v %v %v", next, ok, err)
	}
}

// A manifest whose leaves landed nothing closes with no PR.
func TestAnEmptyManifestClosesWithNoPR(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	gh := recorded(t, map[string]string{
		listPath:    list(node(1, 1, ManifestLabel)),
		subsPath(1): subs(-2),
	})
	s := Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: disk.NewFake()}
	if ok, err := s.Claim(a, 1); err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	l, err := s.Land(a, "", qs, full, func(string) error { t.Fatal("the check ran"); return nil })
	if err != nil || !l.Closed || l.Number != 0 || issueAt(t, gh, 1).State != "closed" || len(pullsIn(t, s)) != 0 {
		t.Fatalf("%+v %v", l, err)
	}
}

// An issue filed into no manifest goes into the open misc manifest, and
// into a new one once the old one's time is up or its PR is open.
func TestAnIssueInNoManifestGoesIntoTheMiscManifest(t *testing.T) {
	t.Parallel()
	c := atNow()
	gh := recordedAt(t, c, map[string]string{"repos/o/r/issues/9": `{"number":9,"state":"closed"}`})
	s := Source{Git: machine, Repo: repo, GitHub: gh, Clock: c}
	in := func(want int, title string) int {
		t.Helper()
		made, _, err := s.Create(title, "b", 0, nil)
		if err != nil {
			t.Fatal(err)
		}
		top, err := s.manifestOf(made.Number)
		if err != nil || (want != 0 && top != want) {
			t.Fatalf("#%d is in #%d (%v), want #%d", made.Number, top, err, want)
		}
		return top
	}
	misc := in(0, "first")
	if m := issueAt(t, gh, misc); !m.labelled(MiscLabel) || !m.labelled(ManifestLabel) || !m.labelled(Label) {
		t.Fatalf("%+v", m)
	}
	c.Advance(ManifestTarget - time.Minute)
	in(misc, "second")
	// The target time from its creation is up: the next one opens.
	c.Advance(time.Minute)
	next := in(0, "third")
	if next == misc {
		t.Fatalf("the misc manifest #%d took an issue after its time", misc)
	}
	// Its PR is open: the next issue waits for the next one.
	seed(t, gh, map[string]string{fmt.Sprintf("repos/o/r/pulls?head=o:issue-%d&base=main&state=open&per_page=100", next): fmt.Sprintf(`[{"number":90,"head":{"ref":"issue-%d"},"base":{"ref":"main"}}]`, next)})
	if again := in(0, "fourth"); again == next || again == misc {
		t.Fatalf("filed into #%d", again)
	}
	// A manifest, and an issue for a person, stand at the top by themselves.
	made, _, err := s.create("a manifest", "b", 0, nil, []string{Label, ManifestLabel})
	if err != nil {
		t.Fatal(err)
	}
	if top, err := s.manifestOf(made.Number); err != nil || top != 0 {
		t.Fatalf("%d %v", top, err)
	}
}

// The pause switch is a config value on main: set there, a box's take
// reads it before it takes anything.
func TestThePauseSwitchIsReadFromMain(t *testing.T) {
	t.Parallel()
	_, a, b := boxes(t)
	s := Source{Git: machine, Repo: repo}
	if paused, err := s.Paused(b); err != nil || paused {
		t.Fatalf("a main without the wiring file: %v %v", paused, err)
	}
	file := filepath.Join(a, index.WiringFile)
	if err := os.MkdirAll(filepath.Dir(file), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(file, []byte("instances:\n  issues: {module: issues, config: {paused: true}}\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, a, "add", ".")
	run(t, a, "commit", "-q", "-m", "pause the fleet")
	run(t, a, "push", "-q", "origin", "main")
	// Box b, started before, reads it from origin/main.
	if paused, err := s.Paused(b); err != nil || !paused {
		t.Fatalf("paused on main: %v %v", paused, err)
	}
	if paused, err := (Source{Git: machine}).Paused(b); err != nil || !paused {
		t.Fatal(err)
	}
}

// A priority leaf in the second manifest makes a take at the top offer it
// before the first, and inside it before its other leaves; a box working the
// first manifest does not drop it for that.
func TestAPriorityLeafPutsItsManifestFirst(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	tree := func(priority ...string) string {
		return list(node(1, 2, ManifestLabel), node(2, 0), node(3, 0), node(4, 2, ManifestLabel), node(5, 0), node(6, 0, priority...))
	}
	gh := recorded(t, unblocked(map[string]string{
		listPath:      tree(),
		subsPath(1):   subs(2, 3),
		subsPath(4):   subs(5, 6),
		refsPath:      `[]`,
		openPullsPath: `[]`,
	}, 1, 2, 3, 4, 5, 6))
	s := Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: disk.NewFake()}
	// With no priority, the lowest manifest comes first, and the box takes it.
	if took, ok, err := s.Take(a, 0); err != nil || !ok || took.Number != 1 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	run(t, a, "checkout", "-q", "main")
	// Now #6, in the second manifest, is labelled se-priority.
	seed(t, gh, map[string]string{listPath: tree(PriorityLabel)})
	next, ok, err := s.Next()
	if err != nil || !ok || next.Number != 4 || !strings.HasPrefix(next.Picked, "A priority manifest") {
		t.Fatalf("next %+v %v %v", next, ok, err)
	}
	if tr, err := s.In(4); err != nil || len(tr.Ready) != 2 || tr.Ready[0].Number != 6 {
		t.Fatalf("inside #4: %+v %v", tr, err)
	}
	// The box working #1 finishes it: its next leaf is #1's, not #6.
	if took, ok, _, err := s.TakeIn(a, 1, 0); err != nil || !ok || took.Number != 2 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
}
