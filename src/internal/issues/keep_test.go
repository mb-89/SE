// Internal test package: it lands on the package's fakes.
package issues

import (
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
)

func TestLandCommitsTheStampWithTheWork(t *testing.T) {
	t.Parallel()
	origin, a := claimed(t)
	gh := landGH(t, map[string]string{pullsPath: `[]`})
	d := disk.NewFake()
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}).Land(a, "", qs, full, battered()); err != nil {
		t.Fatal(err)
	}
	// What CI checks out of the pushed branch carries the stamp naming its tree.
	if _, err := battery.Trusted(machine, origin, "issue-6", battery.Stamp); err != nil {
		t.Fatalf("CI would run the battery again: %v", err)
	}
	if got := run(t, a, "log", "-1", "--format=%s", "--", battery.Stamp); !strings.Contains(got, "stamp") {
		t.Fatalf("the stamp's commit is %q", got)
	}
	if w := gh.Writes(); slices.ContainsFunc(w, func(s string) bool { return strings.Contains(s, "/statuses/") }) {
		t.Fatalf("the land posted a status: %q", w)
	}
}

func TestLandRefusesATreeTheBatteryDidNotPass(t *testing.T) {
	t.Parallel()
	origin, a := claimed(t)
	gh := landGH(t, map[string]string{pullsPath: `[]`})
	d := disk.NewFake()
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}
	// The check passes, but the battery recorded no tree: a dirty worktree, say.
	if _, err := s.Land(a, "", qs, full, passes); err == nil || !strings.Contains(err.Error(), "the battery has not passed issue-6's tree") {
		t.Fatalf("%v", err)
	}
	// It recorded another tree: the work moved on after it ran.
	if err := battered()(a); err != nil {
		t.Fatal(err)
	}
	commitFile(t, a, "later", "x")
	if _, err := s.Land(a, "", qs, full, passes); err == nil || !strings.Contains(err.Error(), "has not passed") {
		t.Fatalf("%v", err)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, origin, "rev-parse", "main"); got != want {
		t.Fatalf("a refused land moved issue-6 to %s", got)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused land wrote %q", w)
	}
}

func TestLandRefusesABranchMainMovedPastWhileTheBatteryRan(t *testing.T) {
	t.Parallel()
	origin, a, b := claimedBy(t)
	gh := landGH(t, map[string]string{pullsPath: `[]`})
	d := disk.NewFake()
	check := func(dir string) error {
		// Another PR merges while the battery runs.
		commitFile(t, b, "other", "b")
		run(t, b, "push", "-q", "origin", "main")
		return battered()(dir)
	}
	_, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}.Land(a, "", qs, full, check)
	if err == nil || !strings.Contains(err.Error(), "main moved past issue-6 while the battery ran") {
		t.Fatalf("%v", err)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, origin, "rev-parse", "main^"); got != want {
		t.Fatalf("a refused land moved issue-6 to %s", got)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused land wrote %q", w)
	}
}

// landedPR is box a's issue-6 landed as PR #7, auto-merge on, with the clock and the disk its battery records on.
func landedPR(t *testing.T) (origin, a, b string, gh *github.Fake, c *clock.Fake, d disk.Disk) {
	t.Helper()
	origin, a, b = claimedBy(t)
	c = clock.NewFake(landedAt())
	gh = recordedAt(t, c, map[string]string{issue6: leaf6, comments6: `[]`, created6: `[{"timestamp":"2026-01-02T10:00:00Z"}]`, pullsPath: `[]`})
	d = disk.NewFake()
	if l, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c, Disk: d}).Land(a, "", qs, full, battered()); err != nil || l.Number != 7 {
		t.Fatalf("%+v %v", l, err)
	}
	return origin, a, b, gh, c, d
}

// The coordinator's loop for one PR: it falls behind main, the box merges
// main in, checks, commits the stamp and pushes, CI trusts the stamp, and
// auto-merge merges it.
func TestTheBoxKeepsAPRThatFallsBehindMainUntilItMerges(t *testing.T) {
	t.Parallel()
	origin, a, b, gh, c, d := landedPR(t)
	// Another PR merges: #7 is behind main, and main's ruleset holds it.
	run(t, b, "checkout", "-q", "main")
	run(t, b, "pull", "-q", "origin", "main")
	commitFile(t, b, "other", "b")
	run(t, b, "push", "-q", "origin", "main")
	checks := 0
	check := func(dir string) error {
		checks++
		return battered()(dir)
	}
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c, Disk: d}
	s.Waits = func(string) {
		// What GitHub does while the box waits: CI on the new head trusts the
		// battery's stamp for its tree, and auto-merge merges it once it is up to date.
		run(t, origin, "merge-base", "--is-ancestor", "main", "issue-6")
		if _, err := battery.Trusted(machine, origin, "issue-6", battery.Stamp); err != nil {
			t.Errorf("CI would run the battery again: %v", err)
			return
		}
		if _, err := gh.Send("PUT", "repos/o/r/pulls/7/merge", github.F("merge_method", "squash")); err != nil {
			t.Error(err)
		}
	}
	k, err := s.Keep(a, time.Hour, check)
	if err != nil {
		t.Fatal(err)
	}
	if want := (Kept{Issue: 6, PR: 7, URL: "https://github.com/o/r/pull/7", Merged: true, Updated: 1}); k != want || checks != 1 {
		t.Fatalf("%+v after %d checks, want %+v", k, checks, want)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, a, "rev-parse", "HEAD"); got != want {
		t.Fatalf("origin's issue-6 is %s, want %s", got, want)
	}
	// Merged in, never rebased: the update is a merge, its stamp committed after it.
	if parents := strings.Fields(run(t, a, "log", "-1", "--format=%P", "HEAD^")); len(parents) != 2 {
		t.Fatalf("the update is no merge: %v", parents)
	}
}

func TestTheBoxKeepsAPRUpToDateUntilItsTimeRunsOutOrAnotherBoxTakesItOver(t *testing.T) {
	t.Parallel()
	_, a, _, gh, c, d := landedPR(t)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c, Disk: d}
	head := run(t, a, "rev-parse", "HEAD")
	k, err := s.Keep(a, 3*time.Minute, func(string) error { t.Error("an up-to-date PR was checked again"); return nil })
	if err != nil || k.Merged || k.TakenOver || k.Updated != 0 || k.PR != 7 {
		t.Fatalf("%+v %v", k, err)
	}
	if got := run(t, a, "rev-parse", "HEAD"); got != head {
		t.Fatalf("an up-to-date PR moved to %s", got)
	}
	s.Waits = func(string) {
		if _, err := gh.Send("POST", "repos/o/r/issues/6/comments", github.F("body", "Took over.\n<!-- se:takeover 1 -->\n<!-- se:box other -->")); err != nil {
			t.Error(err)
		}
	}
	if k, err := s.Keep(a, time.Hour, passes); err != nil || !k.TakenOver || k.Merged {
		t.Fatalf("%+v %v", k, err)
	}
}

func TestKeepRefusesABranchWithoutAnOpenPR(t *testing.T) {
	t.Parallel()
	_, a, _, gh, c, d := landedPR(t)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c, Disk: d}
	if _, err := gh.Send("PATCH", "repos/o/r/pulls/7", github.F("state", "closed")); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Keep(a, time.Hour, passes); err == nil || !strings.Contains(err.Error(), "closed unmerged") {
		t.Fatalf("%v", err)
	}
	_, fresh := claimed(t)
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: landGH(t, map[string]string{}), Clock: c, Disk: d}).Keep(fresh, time.Hour, passes); err == nil || !strings.Contains(err.Error(), "no PR to keep") {
		t.Fatalf("%v", err)
	}
}
