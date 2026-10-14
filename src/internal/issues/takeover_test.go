// Internal test package: it uses the unexported comment type, asks and pause.
package issues

import (
	"fmt"
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

// newPulls is a fake repository with #5 ready and #7 claimed, its PR #70
// answering pr: GitHub computes its mergeability one pause after another,
// so each answer holds from one pause after the one before it.
func newPulls(t *testing.T, c *clock.Fake, pr ...string) *github.Fake {
	t.Helper()
	gh := recordedAt(t, c, unblocked(map[string]string{
		listPath:      `[` + open(5, "new work") + `,` + open(7, "old work") + `]`,
		refsPath:      `[{"ref":"refs/heads/issue-7"}]`,
		openPullsPath: `[{"number":70,"head":{"ref":"issue-7"},"base":{"ref":"main"}},{"number":71,"head":{"ref":"someone-else"},"base":{"ref":"main"}}]`,
		// #7's branch saw a push inside the lease: it is not stuck.
		activity(7): pushed(fresh),
	}, 5, 7))
	for k, p := range pr {
		if err := gh.SeedAt(now.Add(time.Duration(k)*pause), map[string]string{"repos/o/r/pulls/70": p}); err != nil {
			t.Fatal(err)
		}
	}
	return gh
}

// said sets #7's comments to these bodies, oldest first.
func said(t *testing.T, gh *github.Fake, bodies ...string) {
	t.Helper()
	seed(t, gh, map[string]string{"repos/o/r/issues/7/comments": jsonComments(bodies...)})
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
	_, a, _ = boxes(t)
	run(t, a, "checkout", "-q", "-b", "issue-7")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "work on 7")
	run(t, a, "push", "-q", "origin", "issue-7")
	run(t, a, "checkout", "-q", "main")
	run(t, a, "branch", "-q", "-D", "issue-7")
	return a
}

func TestADirtyPRIsTakenOverBeforeNewWork(t *testing.T) {
	t.Parallel()
	a := claimed7(t)
	g := newPulls(t, atNow(), pr70("false", "dirty"))
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 7 || took.Takeover == nil || *took.Takeover != (Takeover{PR: 70, URL: "p70", Count: 1}) {
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
	// The takeover makes #7 final.
	if w := g.Writes(); w[len(w)-1] != "POST repos/o/r/issues/7/labels" || !labelled(t, g, 7, FinalLabel) {
		t.Fatalf("writes %q", w)
	}
	// Named with --take N, the issue named is taken, and no PR is asked.
	g = newPulls(t, atNow())
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
		_, a, _ := boxes(t)
		c := atNow()
		g := newPulls(t, c, answers...)
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
		if err != nil || !ok || took.Number != 5 || took.Takeover != nil || len(commentsAt(t, g, 7)) != 0 {
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
	g := newPulls(t, c, pr70("null", "unknown"), pr70("false", "dirty"))
	if took, ok, err := (Source{Proc: machine, Repo: repo, GitHub: g, Clock: c}).Take(a, 0); err != nil || !ok || took.Number != 7 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
}

// finalSeven is the recorded list with #7 labelled se-final.
func finalSeven(t *testing.T, g *github.Fake) {
	t.Helper()
	seed(t, g, map[string]string{listPath: `[` + open(5, "new work") + `,{"number":7,"title":"old work","state":"open","html_url":"u7","labels":[{"name":"se"},{"name":"se-final"}]}]`})
}

func TestASecondConflictTakeoverIsTakenOverAgain(t *testing.T) {
	t.Parallel()
	a := claimed7(t)
	g := newPulls(t, atNow(), pr70("false", "dirty"))
	finalSeven(t, g)
	// The first takeover found head 0ld; the PR conflicts again at abc.
	said(t, g, "Taken over.\n<!-- se:takeover 1 -->\n<!-- se:takeover-head 0ld -->")
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 7 || took.Takeover == nil || *took.Takeover != (Takeover{PR: 70, URL: "p70", Count: 2}) {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	// Final, it is taken over again: nothing is minted for a person.
	writes := g.Writes()
	for _, w := range writes {
		if w == "POST repos/o/r/issues" || strings.Contains(w, "blocked_by") || strings.Contains(w, "DELETE") {
			t.Fatalf("a final conflict minted or held something: %q", writes)
		}
	}
	if labelled(t, g, 7, PersonLabel) || !labelled(t, g, 7, FinalLabel) {
		t.Fatalf("#7 was labelled for a person, or is no longer final: %q", writes)
	}
	if c := commentsAt(t, g, 7); len(c) != 2 || !strings.Contains(c[1].Body, "<!-- se:takeover 2 -->") || !strings.Contains(c[1].Body, "<!-- se:takeover-head abc -->") {
		t.Fatalf("comments %+v", c)
	}
}

func TestATakeoverInFlightIsLeftToItsBox(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	g := newPulls(t, atNow(), pr70("false", "dirty"))
	// A box took #7 over at this very head and has not landed the merge yet.
	said(t, g, "<!-- se:takeover 1 -->\n<!-- se:takeover-head abc -->")
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 || len(g.Writes()) != 0 {
		t.Fatalf("took %+v %v %v, writes %q", took, ok, err, g.Writes())
	}
}

func TestOfTwoBoxesTakingOverAtOnceTheFirstMarkerWins(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	g := newPulls(t, atNow(), pr70("false", "dirty"))
	other := "<!-- se:takeover 1 -->\n<!-- se:takeover-head abc -->"
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: &racer{g, other}, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	w := g.Writes()
	if c := commentsAt(t, g, 7); len(c) != 1 || c[0].Body != other || w[len(w)-1] != fmt.Sprintf("DELETE repos/o/r/issues/comments/%d", c[0].ID+1) {
		t.Fatalf("the losing marker was not withdrawn: %q, %+v", w, c)
	}
}

func TestAConflictAfterAStuckTakeoverIsTakenOverAgain(t *testing.T) {
	t.Parallel()
	a := claimed7(t)
	g := newPulls(t, atNow(), pr70("false", "dirty"))
	// #7 was taken over once already, stuck, so it is final; its PR now conflicts.
	finalSeven(t, g)
	said(t, g, "<!-- se:takeover 1 -->\nTaken over: nothing was pushed.")
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: g, Clock: atNow()}.Take(a, 0)
	if err != nil || !ok || took.Number != 7 || took.Takeover == nil || took.Takeover.Count != 2 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if c := commentsAt(t, g, 7); len(c) != 2 || !strings.Contains(c[1].Body, "<!-- se:takeover 2 -->") {
		t.Fatalf("comments %+v", c)
	}
}
