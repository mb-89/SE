// Internal test package: it reads the unexported commitStatus and lands on the package's fakes.
package issues

import (
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
)

// statusesOf reads the statuses on commit sha back from the fake GitHub, newest first.
func statusesOf(t *testing.T, gh github.GitHub, sha string) []commitStatus {
	t.Helper()
	got, err := api[commitStatus](Source{Repo: repo, GitHub: gh}, fmt.Sprintf("repos/o/r/commits/%s/statuses?per_page=100", sha), true)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

func TestLandPostsTheBatterysStatusNamingTheTreeItPushed(t *testing.T) {
	t.Parallel()
	origin, a := claimed(t)
	gh := landGH(t, map[string]string{pullsPath: `[]`})
	d := disk.NewFake()
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}).Land(a, "", qs, full, battered(d)); err != nil {
		t.Fatal(err)
	}
	head := run(t, origin, "rev-parse", "issue-6")
	got := statusesOf(t, gh, head)
	if len(got) != 1 || got[0].State != "success" || got[0].Context != BatteryContext || got[0].Description != BatteryDescription(run(t, a, "rev-parse", "HEAD^{tree}")) {
		t.Fatalf("the statuses on %s are %+v", head, got)
	}
}

// noStatuses is GitHub behind a cloud box's proxy, which refuses commit statuses.
type noStatuses struct{ github.GitHub }

func (g noStatuses) Send(method, path string, fields ...github.Field) ([]byte, error) {
	if strings.Contains(path, "/statuses/") {
		return nil, &github.Error{Status: 403, Message: "Write access to this GitHub API path is not permitted through this proxy"}
	}
	return g.GitHub.Send(method, path, fields...)
}

// A refused status stops nothing: the land posts the answers, opens the PR
// and turns on auto-merge, and names the refusal, since CI checks the commit.
func TestARefusedStatusIsAWarningAndTheLandGoesOn(t *testing.T) {
	t.Parallel()
	_, a := claimed(t)
	gh := landGH(t, map[string]string{pullsPath: `[]`})
	d := disk.NewFake()
	l, err := Source{Proc: machine, Repo: repo, GitHub: noStatuses{gh}, Clock: atNow(), Disk: d}.Land(a, "", qs, full, battered(d))
	if err != nil || !l.Created || l.Number == 0 || !strings.Contains(l.Warning, "403") && !strings.Contains(l.Warning, "not permitted") {
		t.Fatalf("%+v %v", l, err)
	}
	if len(commentsAt(t, gh, 6)) != 1 || pullOf(t, gh, l.Number)["auto_merge"] == nil {
		t.Fatalf("the land stopped at the refused status: %+v", l)
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
	if err := battered(d)(a); err != nil {
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
		return battered(d)(dir)
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

const (
	sha1  = "1111111111111111111111111111111111111111"
	treeT = "2222222222222222222222222222222222222222"
)

func TestCITrustsTheBatterysStatusFromAWriterForItsTree(t *testing.T) {
	t.Parallel()
	gh := recorded(t, map[string]string{"repos/o/r/collaborators/reader/permission": `{"permission":"read"}`})
	s := Source{Repo: repo, GitHub: gh, Clock: atNow()}
	post := func(state, description string) {
		t.Helper()
		if _, err := gh.Send("POST", "repos/o/r/statuses/"+sha1, github.F("state", state), github.F("context", BatteryContext), github.F("description", description)); err != nil {
			t.Fatal(err)
		}
	}
	// A person's push without SE carries none: asked again, then refused.
	if _, err := s.Trusted(sha1, treeT); err == nil || !strings.Contains(err.Error(), "carries no se/battery status") {
		t.Fatalf("%v", err)
	}
	if n := len(gh.Writes()); n != 0 {
		t.Fatalf("trust wrote %d times", n)
	}
	post("success", BatteryDescription(treeT))
	if why, err := s.Trusted(sha1, treeT); err != nil || !strings.Contains(why, "posted by se-fake") {
		t.Fatalf("%q %v", why, err)
	}
	// The checkout holds another tree: main moved, and the merge is not what the battery ran.
	if _, err := s.Trusted(sha1, "3333333333333333333333333333333333333333"); err == nil || !strings.Contains(err.Error(), "its checkout holds tree 3333") {
		t.Fatalf("%v", err)
	}
	// The latest status counts.
	post("failure", BatteryDescription(treeT))
	if _, err := s.Trusted(sha1, treeT); err == nil || !strings.Contains(err.Error(), "is failure, not success") {
		t.Fatalf("%v", err)
	}
	// One posted by an account that only reads is not trusted.
	gh.Login = "reader"
	post("success", BatteryDescription(treeT))
	if _, err := s.Trusted(sha1, treeT); err == nil || !strings.Contains(err.Error(), "has read access") {
		t.Fatalf("%v", err)
	}
}

func TestCIAsksAgainForAStatusTheBoxPostsJustAfterItsPush(t *testing.T) {
	t.Parallel()
	c := atNow()
	gh := recordedAt(t, c, map[string]string{})
	asked := 0
	s := Source{Repo: repo, GitHub: gh, Clock: c, Waits: func(string) {
		if asked++; asked == 1 {
			if _, err := gh.Send("POST", "repos/o/r/statuses/"+sha1, github.F("state", "success"), github.F("context", BatteryContext), github.F("description", BatteryDescription(treeT))); err != nil {
				t.Error(err)
			}
		}
	}}
	if _, err := s.Trusted(sha1, treeT); err != nil || asked != 1 {
		t.Fatalf("asked %d: %v", asked, err)
	}
}

// landedPR is box a's issue-6 landed as PR #7, auto-merge on, with the clock and the disk its battery records on.
func landedPR(t *testing.T) (origin, a, b string, gh *github.Fake, c *clock.Fake, d disk.Disk) {
	t.Helper()
	origin, a, b = claimedBy(t)
	c = clock.NewFake(landedAt())
	gh = recordedAt(t, c, map[string]string{issue6: leaf6, comments6: `[]`, created6: `[{"timestamp":"2026-01-02T10:00:00Z"}]`, pullsPath: `[]`})
	d = disk.NewFake()
	if l, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c, Disk: d}).Land(a, "", qs, full, battered(d)); err != nil || l.Number != 7 {
		t.Fatalf("%+v %v", l, err)
	}
	return origin, a, b, gh, c, d
}

// The coordinator's loop for one PR: it falls behind main, the box merges
// main in, checks, pushes and posts the status, CI trusts it, and auto-merge
// merges it.
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
		return battered(d)(dir)
	}
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c, Disk: d}
	s.Waits = func(string) {
		// What GitHub does while the box waits: CI on the new head trusts the
		// battery's status for its tree, and auto-merge merges it once it is up to date.
		head := run(t, origin, "rev-parse", "issue-6")
		run(t, origin, "merge-base", "--is-ancestor", "main", "issue-6")
		if _, err := s.Trusted(head, run(t, origin, "rev-parse", "issue-6^{tree}")); err != nil {
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
	// Merged in, never rebased: the landed commit is still on the branch.
	if parents := strings.Fields(run(t, a, "log", "-1", "--format=%P")); len(parents) != 2 {
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
