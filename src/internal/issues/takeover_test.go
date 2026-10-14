// Internal test package: it uses the unexported comment type, asks and pause.
package issues

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"testing"
)

const (
	openPullsPath = "repos/o/r/pulls?base=main&state=open&per_page=100"
	comments7     = "repos/o/r/issues/7/comments?per_page=100"
)

// pr70 is #7's PR at head abc as GitHub reports it: mergeable is "null",
// "true" or "false", with its mergeable_state.
func pr70(mergeable, state string) string {
	return fmt.Sprintf(`{"number":70,"html_url":"p70","mergeable":%s,"mergeable_state":%q,"head":{"ref":"issue-7","sha":"abc"}}`, mergeable, state)
}

// pulls is a recorded repository with #5 ready and #7 claimed, its PR #70
// answering pr. It keeps #7's comments, so a takeover's marker is written and
// read back, and every write it was asked.
type pulls struct {
	t        *testing.T
	answers  map[string]string
	pr       []string // #70 as asked, one answer per ask; the last repeats
	comments []comment
	// before is a comment another box writes just before this one's.
	before *comment
	writes [][]string
}

func newPulls(t *testing.T, pr ...string) *pulls {
	g := &pulls{t: t, pr: pr, answers: unblocked(map[string]string{
		listPath:      `[` + open(5, "new work") + `,` + open(7, "old work") + `]`,
		refsPath:      `[{"ref":"refs/heads/issue-7"}]`,
		openPullsPath: `[{"number":70,"head":{"ref":"issue-7"}},{"number":71,"head":{"ref":"someone-else"}}]`,
		// #7's branch saw a push inside the lease: it is not stuck.
		activity(7): pushed(fresh),
	}, 5, 7)}
	return g
}

func (g *pulls) gh(args ...string) ([]byte, error) {
	g.t.Helper()
	path := args[len(args)-1]
	if args[1] == "-X" {
		g.writes = append(g.writes, args)
		if args[2] == "POST" && path == "repos/o/r/issues/7/comments" {
			if g.before != nil {
				g.comments = append(g.comments, *g.before)
			}
			c := comment{ID: int64(100 + len(g.comments)), Body: strings.TrimPrefix(args[4], "body=")}
			g.comments = append(g.comments, c)
			return json.Marshal(c)
		}
		// The issue for a person a final conflict mints.
		if args[2] == "POST" && path == "repos/o/r/issues" {
			return []byte(`{"number":101,"id":1010,"html_url":"u101"}`), nil
		}
		return []byte(`{}`), nil
	}
	switch path {
	case "repos/o/r/pulls/70":
		a := g.pr[0]
		if len(g.pr) > 1 {
			g.pr = g.pr[1:]
		}
		return []byte(a), nil
	case comments7:
		return json.Marshal(append([]comment{}, g.comments...))
	}
	a, ok := g.answers[path]
	if !ok {
		g.t.Fatalf("gh %v was not recorded", args)
	}
	return []byte(a), nil
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

func noPause(t *testing.T) *int {
	paused := 0
	old := pause
	pause = func() { paused++ }
	t.Cleanup(func() { pause = old })
	return &paused
}

func TestADirtyPRIsTakenOverBeforeNewWork(t *testing.T) {
	noPause(t)
	a := claimed7(t)
	g := newPulls(t, pr70("false", "dirty"))
	took, ok, err := Source{Repo: repo, GH: g.gh, Now: clock}.Take(a, 0)
	if err != nil || !ok || took.Number != 7 || took.Takeover == nil || *took.Takeover != (Takeover{PR: 70, URL: "p70", Count: 1}) {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if got := run(t, a, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-7" {
		t.Fatalf("a is on %s", got)
	}
	if got := run(t, a, "log", "-1", "--format=%s"); got != "work on 7" {
		t.Fatalf("issue-7 is not checked out as it stands: %s", got)
	}
	if len(g.comments) != 1 || !strings.Contains(g.comments[0].Body, "<!-- se:takeover 1 -->") || !strings.Contains(g.comments[0].Body, "<!-- se:takeover-head abc -->") {
		t.Fatalf("comments %+v", g.comments)
	}
	// The takeover makes #7 final.
	if w := g.writes[len(g.writes)-1]; !reflect.DeepEqual(w, []string{"api", "-X", "POST", "-f", "labels[]=se-final", "repos/o/r/issues/7/labels"}) {
		t.Fatalf("writes %q", g.writes)
	}
	// Named with --take N, the issue named is taken, and no PR is asked.
	g = newPulls(t)
	_, b, _ := boxes(t)
	if took, ok, err := (Source{Repo: repo, GH: g.gh, Now: clock}).Take(b, 5); err != nil || !ok || took.Number != 5 || took.Takeover != nil {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
}

func TestACleanOrUnknownPRIsNoConflict(t *testing.T) {
	for name, answers := range map[string][]string{
		"clean":            {pr70("true", "clean")},
		"blocked":          {pr70("false", "blocked")},
		"null, then clean": {pr70("null", "unknown"), pr70("true", "clean")},
		"null, every time": {pr70("null", "unknown")},
	} {
		paused := noPause(t)
		_, a, _ := boxes(t)
		g := newPulls(t, answers...)
		took, ok, err := Source{Repo: repo, GH: g.gh, Now: clock}.Take(a, 0)
		if err != nil || !ok || took.Number != 5 || took.Takeover != nil || len(g.comments) != 0 {
			t.Errorf("%s: took %+v %v %v", name, took, ok, err)
		}
		if strings.HasPrefix(name, "null") && *paused == 0 {
			t.Errorf("%s: a null answer was not asked again", name)
		}
		if *paused > asks-1 {
			t.Errorf("%s: asked %d times", name, *paused+1)
		}
	}
	// A null answer that turns dirty is a conflict.
	noPause(t)
	a := claimed7(t)
	g := newPulls(t, pr70("null", "unknown"), pr70("false", "dirty"))
	if took, ok, err := (Source{Repo: repo, GH: g.gh, Now: clock}).Take(a, 0); err != nil || !ok || took.Number != 7 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
}

// finalSeven is the recorded list with #7 labelled se-final.
func finalSeven(g *pulls) {
	g.answers[listPath] = `[` + open(5, "new work") + `,{"number":7,"title":"old work","state":"open","html_url":"u7","labels":[{"name":"se"},{"name":"se-final"}]}]`
}

func TestASecondConflictTakeoverWaitsOnAnIssueForAPerson(t *testing.T) {
	noPause(t)
	_, a, _ := boxes(t)
	g := newPulls(t, pr70("false", "dirty"))
	finalSeven(g)
	// The first takeover found head 0ld; the PR conflicts again at abc.
	g.comments = []comment{{ID: 1, Body: "Taken over.\n<!-- se:takeover 1 -->\n<!-- se:takeover-head 0ld -->"}}
	took, ok, err := Source{Repo: repo, GH: g.gh, Now: clock}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	// #7 itself is not given to a person: an issue for one, #101, blocks it.
	var writes []string
	for _, w := range g.writes {
		writes = append(writes, strings.Join(w[2:], " "))
	}
	for _, want := range []string{
		"POST -f assignees[]=o repos/o/r/issues/101/assignees",
		"POST -F issue_id=1010 repos/o/r/issues/7/dependencies/blocked_by",
		"DELETE repos/o/r/issues/7/labels/se-final",
	} {
		if !contains(writes, want) {
			t.Errorf("not written: %s (writes %q)", want, writes)
		}
	}
	for _, w := range writes {
		if strings.Contains(w, "se-person repos/o/r/issues/7/") {
			t.Fatalf("#7 was labelled for a person: %q", writes)
		}
	}
	if len(g.comments) != 2 || !strings.Contains(g.comments[1].Body, "blocked by #101") || !strings.HasSuffix(g.comments[1].Body, "<!-- se:resume -->") {
		t.Fatalf("comments %+v", g.comments)
	}
	// Blocked by #101, #7's claim waits, and is not stuck.
	got := survey(t, unblocked(map[string]string{
		listPath: `[{"number":7,"state":"open","labels":[{"name":"se"}]}]`,
		refsPath: `[{"ref":"refs/heads/issue-7"}]`,
		links(7): `[{"number":101,"state":"open"}]`,
	}))
	if got[7] != "issue-7 waits: blocked by #101" {
		t.Fatalf("%v", got)
	}
}

func TestATakeoverInFlightIsLeftToItsBox(t *testing.T) {
	noPause(t)
	_, a, _ := boxes(t)
	g := newPulls(t, pr70("false", "dirty"))
	// A box took #7 over at this very head and has not landed the merge yet.
	g.comments = []comment{{ID: 1, Body: "<!-- se:takeover 1 -->\n<!-- se:takeover-head abc -->"}}
	took, ok, err := Source{Repo: repo, GH: g.gh, Now: clock}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 || len(g.writes) != 0 {
		t.Fatalf("took %+v %v %v, writes %q", took, ok, err, g.writes)
	}
}

func TestOfTwoBoxesTakingOverAtOnceTheFirstMarkerWins(t *testing.T) {
	noPause(t)
	_, a, _ := boxes(t)
	g := newPulls(t, pr70("false", "dirty"))
	g.before = &comment{ID: 50, Body: "<!-- se:takeover 1 -->\n<!-- se:takeover-head abc -->"}
	took, ok, err := Source{Repo: repo, GH: g.gh, Now: clock}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	last := g.writes[len(g.writes)-1]
	if strings.Join(last, " ") != "api -X DELETE repos/o/r/issues/comments/101" {
		t.Fatalf("the losing marker was not withdrawn: %q", g.writes)
	}
}

func TestAConflictAfterAStuckTakeoverGoesToAPerson(t *testing.T) {
	noPause(t)
	_, a, _ := boxes(t)
	g := newPulls(t, pr70("false", "dirty"))
	// #7 was taken over once already, stuck, so it is final; its PR now conflicts.
	finalSeven(g)
	g.comments = []comment{{ID: 1, Body: "<!-- se:takeover 1 -->\nTaken over: nothing was pushed."}}
	took, ok, err := Source{Repo: repo, GH: g.gh, Now: clock}.Take(a, 0)
	if err != nil || !ok || took.Number != 5 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if len(g.comments) != 2 || !strings.HasPrefix(g.comments[1].Body, "<!-- se:person -->\nPR #70 conflicts with main on its final attempt") {
		t.Fatalf("comments %+v", g.comments)
	}
}
