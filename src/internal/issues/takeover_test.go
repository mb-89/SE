// Internal test package: it uses the unexported comment type, asks and pause.
package issues

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"

	"github.com/mb-89/SE/src/internal/io/github"
)

const (
	openPullsPath = "repos/o/r/pulls?state=open&per_page=100"
	comments7     = "repos/o/r/issues/7/comments?per_page=100"
)

// pr70 is #7's PR at head abc as GitHub reports it: mergeable is "null",
// "true" or "false", with its mergeable_state.
func pr70(mergeable, state string) string {
	return fmt.Sprintf(`{"number":70,"html_url":"p70","mergeable":%s,"mergeable_state":%q,"head":{"ref":"issue-7","sha":"abc"},"base":{"ref":"main"}}`, mergeable, state)
}

// newPulls is a fake repository with #5 ready and #7 claimed, its branch
// last pushed at when (empty: GitHub keeps no record of a push), its PR #70
// answering pr: GitHub computes its mergeability one pause after another,
// so each answer holds from one pause after the one before it.
func newPulls(t *testing.T, c *clock.Fake, when string, pr ...string) *github.Fake {
	t.Helper()
	gh := recordedAt(t, c, unblocked(map[string]string{
		// #5 is a retro, a leaf a take at the top may have: boxes take
		// only manifests, retros and overhauls there.
		listPath:      `[` + openRetro(5, "new work") + `,` + open(7, "old work") + `]`,
		refsPath:      `[{"ref":"refs/heads/issue-7"}]`,
		openPullsPath: `[{"number":70,"head":{"ref":"issue-7"},"base":{"ref":"main"}},{"number":71,"head":{"ref":"someone-else"},"base":{"ref":"main"}}]`,
		activity(7):   `[]`,
	}, 5, 7))
	if when != "" {
		seed(t, gh, map[string]string{activity(7): pushed(when)})
	}
	for k, p := range pr {
		if err := gh.SeedAt(now.Add(time.Duration(k)*pause), map[string]string{"repos/o/r/pulls/70": p}); err != nil {
			t.Fatal(err)
		}
	}
	return gh
}

// lately sets #7's comments to these bodies, oldest first, each made within
// the lease, so a takeover they record keeps #7 from being stuck.
func lately(t *testing.T, gh *github.Fake, bodies ...string) {
	t.Helper()
	var parts []string
	for k, b := range bodies {
		parts = append(parts, fmt.Sprintf(`{"id":%d,"body":%q,"created_at":%q}`, 100+k, b, fresh))
	}
	seed(t, gh, map[string]string{"repos/o/r/issues/7/comments": "[" + strings.Join(parts, ",") + "]"})
}

// racer is GitHub with another box that posts its takeover marker on #7
// just before this one's.
type racer struct {
	*github.Fake
	marker string
}

func (r *racer) Send(method, path string, fields ...github.Field) ([]byte, error) {
	if method == "POST" && path == "repos/o/r/issues/7/comments" && r.marker != "" {
		if _, err := r.Fake.Send(method, path, github.F("body", r.marker)); err != nil {
			return nil, err
		}
		r.marker = ""
	}
	return r.Fake.Send(method, path, fields...)
}

// claimed7 makes origin's issue-7, with one commit of work on it.
func claimed7(t *testing.T) (a string) {
	t.Helper()
	return claimedAt(t, 7)
}

// claimedAt makes origin's issue-n, with one commit of work on it.
func claimedAt(t *testing.T, n int) (a string) {
	t.Helper()
	_, a, _ = boxes(t)
	b := fmt.Sprintf("issue-%d", n)
	run(t, a, "checkout", "-q", "-b", b)
	run(t, a, "commit", "-q", "--allow-empty", "-m", fmt.Sprintf("work on %d", n))
	run(t, a, "push", "-q", "origin", b)
	run(t, a, "checkout", "-q", "main")
	run(t, a, "branch", "-q", "-D", b)
	return a
}

func TestADirtyPRIsTakenOverBeforeNewWork(t *testing.T) {
	t.Parallel()
	a := claimed7(t)
	// Nothing was pushed to issue-7 within the lease: no box works it.
	g := newPulls(t, atNow(), stale, pr70("false", "dirty"))
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 7 || took.Takeover == nil || !reflect.DeepEqual(*took.Takeover, Takeover{PR: 70, URL: "p70", Count: 1}) {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if got := run(t, a, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-7" {
		t.Fatalf("a is on %s", got)
	}
	if got := run(t, a, "log", "-1", "--format=%s"); got != "work on 7" {
		t.Fatalf("issue-7 is not checked out as it stands: %s", got)
	}
	if c := commentsAt(t, g, 7); len(c) != 1 || !strings.Contains(c[0].Body, "<!-- se:takeover 1 -->") || !strings.Contains(c[0].Body, "<!-- se:takeover-head abc -->") {
		t.Fatalf("comments %+v", c)
	}
	// A conflict is no failure: the takeover does not make #7 final.
	if w := g.Writes(); contains(w, "POST repos/o/r/issues/7/labels") || labelled(t, g, 7, FinalLabel) {
		t.Fatalf("writes %q", w)
	}
	// Named with --take N, the issue named is taken, and no PR is asked.
	g = newPulls(t, atNow(), stale)
	_, b, _ := boxes(t)
	if took, ok, err := (Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}).Take(b, 5); err != nil || !ok || took.Number != 5 || took.Takeover != nil {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
}

func TestACleanOrUnknownPRIsNoConflict(t *testing.T) {
	t.Parallel()
	for name, answers := range map[string][]string{
		"clean":            {pr70("true", "clean")},
		"blocked":          {pr70("false", "blocked")},
		"null, then clean": {pr70("null", "unknown"), pr70("true", "clean")},
		"null, every time": {pr70("null", "unknown")},
	} {
		a := claimed7(t)
		c := atNow()
		g := newPulls(t, c, stale, answers...)
		// Each pause is told before it begins: the clock has not moved past the pauses told before it.
		var told []string
		waits := func(note string) {
			if at := c.Now().Sub(now); at != time.Duration(len(told))*pause {
				t.Errorf("%s: told %q only %s in", name, note, at)
			}
			told = append(told, note)
		}
		took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: c, Waits: waits}.Take(a, 0)
		paused := int(c.Now().Sub(now) / pause)
		if len(told) != paused || paused > 0 && !strings.Contains(told[0], "PR #70") {
			t.Errorf("%s: paused %d times, told %q", name, paused, told)
		}
		// No conflict: #7, stale, is taken over as stuck work, not for its PR.
		if err != nil || !ok || took.Number != 7 || took.Takeover == nil || took.Takeover.PR != 0 || strings.Contains(commentsAt(t, g, 7)[0].Body, "se:takeover-head") {
			t.Errorf("%s: took %+v %v %v", name, took, ok, err)
		}
		if strings.HasPrefix(name, "null") && paused == 0 {
			t.Errorf("%s: a null answer was not asked again", name)
		}
		if paused > asks-1 {
			t.Errorf("%s: asked %d times", name, paused+1)
		}
	}
	// A null answer that turns dirty is a conflict.
	a := claimed7(t)
	c := atNow()
	g := newPulls(t, c, stale, pr70("null", "unknown"), pr70("false", "dirty"))
	if took, ok, err := (Source{Proc: machine, Repo: repo, GitHub: g, Clock: c}).Take(a, 0); err != nil || !ok || took.Number != 7 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
}

// finalSeven is the recorded list with #7 labelled se-final.
func finalSeven(t *testing.T, g *github.Fake) {
	t.Helper()
	seed(t, g, map[string]string{listPath: `[` + openRetro(5, "new work") + `,{"number":7,"title":"old work","state":"open","html_url":"u7","labels":[{"name":"se"},{"name":"se-final"}]}]`})
}

func TestAFinalIssueInConflictIsTakenOverAgain(t *testing.T) {
	t.Parallel()
	a := claimed7(t)
	g := newPulls(t, atNow(), "", pr70("false", "dirty"))
	finalSeven(t, g)
	// The first takeover found head 0ld; the PR conflicts again at abc. Main
	// moved, which is no failure: #7 is taken over again, not held.
	lately(t, g, "Taken over.\n<!-- se:takeover 1 -->\n<!-- se:takeover-head 0ld -->")
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 7 || took.Takeover == nil || took.Takeover.Count != 2 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if w := g.Writes(); contains(w, "POST repos/o/r/issues") || contains(w, "POST repos/o/r/issues/7/dependencies/blocked_by") {
		t.Fatalf("a conflict minted a hold: %q", w)
	}
}

// Recorded from mb-89/SE on 14 October: #116's PR #118 and #122's PR #140
// each conflicted again within 10 minutes of a conflict takeover, as main
// merged fast, and each went to a person. A conflict at a new head is taken
// over again, and nothing is held.
func TestASecondConflictAtANewHeadIsTakenOverAgain(t *testing.T) {
	t.Parallel()
	a := claimed7(t)
	g := newPulls(t, atNow(), "", pr70("false", "dirty"))
	// The first takeover found head 0ld; the PR conflicts again at abc.
	lately(t, g, "Taken over.\n<!-- se:takeover 1 -->\n<!-- se:takeover-head 0ld -->")
	s := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}
	took, ok, err := s.Take(a, 0)
	if err != nil || !ok || took.Number != 7 || took.Takeover == nil || !reflect.DeepEqual(*took.Takeover, Takeover{PR: 70, URL: "p70", Count: 2}) {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	for _, w := range g.Writes() {
		if strings.Contains(w, "assignees") || strings.Contains(w, "blocked_by") || strings.Contains(w, "labels") {
			t.Fatalf("#7 was held or labelled: %q", g.Writes())
		}
	}
	if c := commentsAt(t, g, 7); len(c) != 2 || !strings.Contains(c[1].Body, "<!-- se:takeover 2 -->\n<!-- se:takeover-head abc -->") {
		t.Fatalf("comments %+v", c)
	}
}

func TestATakeoverInFlightIsLeftToItsBox(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	g := newPulls(t, atNow(), "", pr70("false", "dirty"))
	// A box took #7 over at this very head and has not landed the merge yet.
	lately(t, g, "<!-- se:takeover 1 -->\n<!-- se:takeover-head abc -->")
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 || len(g.Writes()) != 0 {
		t.Fatalf("took %+v %v %v, writes %q", took, ok, err, g.Writes())
	}
}

func TestOfTwoBoxesTakingOverAtOnceTheFirstMarkerWins(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	g := newPulls(t, atNow(), "", pr70("false", "dirty"))
	// A takeover of #7 at an older head, within the lease, keeps it from being stuck.
	lately(t, g, "<!-- se:takeover 1 -->\n<!-- se:takeover-head 0ld -->")
	other := "<!-- se:takeover 2 -->\n<!-- se:takeover-head abc -->"
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: &racer{g, other}, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	w := g.Writes()
	if c := commentsAt(t, g, 7); len(c) != 2 || c[1].Body != other || w[len(w)-1] != fmt.Sprintf("DELETE repos/o/r/issues/comments/%d", c[1].ID+1) {
		t.Fatalf("the losing marker was not withdrawn: %q, %+v", w, c)
	}
}

func TestAConflictAfterAStuckTakeoverIsTakenOver(t *testing.T) {
	t.Parallel()
	a := claimed7(t)
	g := newPulls(t, atNow(), "", pr70("false", "dirty"))
	// #7 was taken over once already, stuck, so it is final; its PR now conflicts.
	finalSeven(t, g)
	lately(t, g, "<!-- se:takeover 1 -->\nTaken over: nothing was pushed.")
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 7 || took.Takeover == nil || took.Takeover.Count != 2 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	// The conflict changed nothing: #7 stays final, and nothing is held.
	if c := commentsAt(t, g, 7); len(c) != 2 || strings.Contains(c[1].Body, "se:person") || !labelled(t, g, 7, FinalLabel) {
		t.Fatalf("comments %+v, writes %q", c, g.Writes())
	}
}

func TestATakeoverWithNoPRSaysSoAndItsLastPush(t *testing.T) {
	t.Parallel()
	if got := (Takeover{}).Line("issue-6"); got != "Where it stands: no open PR from issue-6; GitHub keeps no record of a push to issue-6." {
		t.Fatal(got)
	}
	at := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	if got := (Takeover{Pushed: at, Pull: &PullState{Number: 9, Head: "abc", Mergeable: "clean"}}).Line("issue-6"); got != "Where it stands: PR #9 is clean at abc; no check ran on its head; last pushed to issue-6 at 2026-01-02T03:04:05Z." {
		t.Fatal(got)
	}
}

func TestAConflictPushedToWithinTheLeaseIsRefused(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	// A live box pushed to issue-7 an hour ago: its conflict is its own.
	g := newPulls(t, atNow(), fresh, pr70("false", "dirty"))
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 || took.Takeover != nil {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if c := commentsAt(t, g, 7); len(c) != 0 || labelled(t, g, 7, FinalLabel) {
		t.Fatalf("#7 was taken over: %+v", c)
	}
}

func TestATakeoverNamesItsBranchsCommitsOfAnotherClosedIssue(t *testing.T) {
	t.Parallel()
	gh := recordedAt(t, clock.NewFake(time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)), map[string]string{
		"repos/o/r/issues/3":                         `{"number":3,"state":"open","sub_issues_summary":{"total":1}}`,
		"repos/o/r/issues/3/sub_issues?per_page=100": `[{"number":6,"state":"open"}]`,
		"repos/o/r/compare/issue-3...issue-6?per_page=100": `{"commits":[` +
			`{"sha":"aaaaaaaaaa","commit":{"message":"Stale form of the fix (#4)\n\nBody naming #9."}},` +
			`{"sha":"bbbbbbbbbb","commit":{"message":"Merge origin/issue-5 into issue-6"}},` +
			`{"sha":"cccccccccc","commit":{"message":"Merge origin/issue-3 into issue-6"}},` +
			`{"sha":"dddddddddd","commit":{"message":"Own work for issue-6, see #8"}},` +
			`{"sha":"eeeeeeeeee","commit":{"message":"No issue named"}}]}`,
		"repos/o/r/issues/4":           `{"number":4,"state":"closed"}`,
		"repos/o/r/issues/5":           `{"number":5,"state":"closed"}`,
		"repos/o/r/issues/8":           `{"number":8,"state":"open"}`,
		"repos/o/r/commits/aaaaaaaaaa": `{"files":[{"filename":"a.go"},{"filename":"b.md"}]}`,
		"repos/o/r/commits/bbbbbbbbbb": `{"files":[{"filename":"c.go"}]}`,
	})
	s := Source{Repo: repo, GitHub: gh}
	base, got, err := s.foreign(6)
	want := []Foreign{
		{SHA: "aaaaaaaaaa", Subject: "Stale form of the fix (#4)", Issue: 4, Files: []string{"a.go", "b.md"}},
		{SHA: "bbbbbbbbbb", Subject: "Merge origin/issue-5 into issue-6", Issue: 5, Files: []string{"c.go"}},
	}
	if err != nil || base != "issue-3" || !reflect.DeepEqual(got, want) {
		t.Fatalf("%q %+v %v", base, got, err)
	}
	// A branch GitHub does not hold, at the top: main is its base, and nothing is named.
	if base, got, err := s.foreign(7); err != nil || base != "main" || got != nil {
		t.Fatalf("%q %+v %v", base, got, err)
	}
}
