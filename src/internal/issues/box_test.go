// Internal test package: it drives fanOut and the box count, unexported.
package issues

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// fired counts the fires a fan-out made.
type fired int

func (f *fired) fire() string { *f++; return "fired" }

func TestABoxUnderItsCapTakesTheIssueAndNothingFires(t *testing.T) {
	t.Parallel()
	var f fired
	// A take or a new ready issue with a box alive and under its cap.
	if got := fanOut(map[string]int{"s1": 4, "s2": 1}, 4, true, f.fire); f != 0 || !strings.Contains(got, "s2 runs 1 of its 4") {
		t.Fatalf("%d fires: %q", f, got)
	}
	// Every alive box runs its cap and another issue is ready: one fire.
	if got := fanOut(map[string]int{"s1": 4, "#7": 4}, 4, true, f.fire); f != 1 || got != "fired" {
		t.Fatalf("%d fires: %q", f, got)
	}
	// None is alive: a restart, one fire.
	if got := fanOut(map[string]int{}, 4, true, f.fire); f != 2 || got != "fired" {
		t.Fatalf("%d fires: %q", f, got)
	}
	// Nothing else is ready: nothing fires, however full the boxes.
	if got := fanOut(map[string]int{"s1": 4}, 4, false, f.fire); f != 2 || !strings.Contains(got, "no other issue is ready") {
		t.Fatalf("%d fires: %q", f, got)
	}
}

func TestTheBoxesAreCountedFromTheAliveClaims(t *testing.T) {
	t.Parallel()
	g := newHub(t, pushedAt(unblocked(map[string]string{
		listPath: list(node(1, 0), node(2, 0), node(3, 0), node(4, 0), node(5, 0)),
		refsPath: refs(1, 2, 3, 4),
	}, 5), fresh, 1, 2, 3))
	seed(t, g.Fake, pushedAt(map[string]string{}, stale, 4))
	g.say(1, (Source{Box: "s1"}).boxNote())
	g.say(2, (Source{Box: "s2"}).boxNote())
	// A takeover moves #2 to s1: the last mark names the box.
	g.say(2, "Taken over"+(Source{Box: "s1"}).boxLine())
	s := g.source()
	s.Parallel = 2
	all, err := s.Survey()
	if err != nil {
		t.Fatal(err)
	}
	// #3's claim carries no mark: a box of its own, at its cap. #4 is
	// stuck: its box is not alive.
	got, err := s.boxes(all, nil)
	if err != nil || len(got) != 2 || got["s1"] != 2 || got["#3"] != 2 {
		t.Fatalf("%v %v", got, err)
	}
	// #1's PR is up with auto-merge on: its sub-agent is done, and s1 runs one.
	up := openPull{AutoMerge: &json.RawMessage{'{', '}'}}
	up.Head.Ref, up.Base.Ref = "issue-1", "main"
	if got, err := s.boxes(all, []openPull{up}); err != nil || got["s1"] != 1 {
		t.Fatalf("%v %v", got, err)
	}
	var f fired
	// #5 is ready and every alive box is full: one fire.
	if note := s.FanOut(f.fire, false); f != 1 || note != "fired" {
		t.Fatalf("%d fires: %q", f, note)
	}
	// A box that takes counts as alive with room.
	s.Box = "s3"
	if note := s.FanOut(f.fire, true); f != 1 || !strings.Contains(note, "s3 runs 0 of its 2") {
		t.Fatalf("%d fires: %q", f, note)
	}
}

func TestABoxRunsItsCapAndPullsTheNextWhenOneLands(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	answers := pushedAt(unblocked(map[string]string{
		listPath: list(node(1, 0), node(2, 0), node(3, 0)),
		refsPath: `[]`,
	}, 1, 2, 3), fresh)
	g := newHub(t, answers)
	s := g.source()
	s.Box, s.Worktrees, s.Parallel = "s1", true, 2
	claims := []int{}
	take := func() (Issue, bool, error) {
		took, ok, err := s.Take(a, 0)
		if ok {
			claims = append(claims, took.Number)
			// GitHub now lists the claim's branch, pushed just now.
			seed(t, g.Fake, pushedAt(map[string]string{refsPath: refs(claims...)}, fresh, claims...))
		}
		return took, ok, err
	}
	for _, want := range []int{1, 2} {
		if took, ok, err := take(); err != nil || !ok || took.Number != want {
			t.Fatalf("took %+v %v %v", took, ok, err)
		}
	}
	// The box checked nothing out: its sub-agents work in worktrees.
	if got := run(t, a, "rev-parse", "--abbrev-ref", "HEAD"); got != "main" {
		t.Fatalf("a is on %s", got)
	}
	run(t, a, "rev-parse", "origin/issue-2")
	if !strings.Contains(g.comments(1)[0].Body, "<!-- se:box s1 -->") {
		t.Fatalf("%+v", g.comments(1))
	}
	// Two sub-agents run, the cap: the third take is refused.
	if _, _, err := take(); !IsFull(err) || err.Error() != "this box runs 2 of its 2 sub-agents: pull again when one lands" {
		t.Fatalf("%v", err)
	}
	// #1 lands: its issue closes, and the box pulls #3.
	if _, err := g.Send("PATCH", "repos/o/r/issues/1", github.F("state", "closed")); err != nil {
		t.Fatal(err)
	}
	seed(t, g.Fake, map[string]string{listPath: list(node(2, 0), node(3, 0))})
	if took, ok, err := take(); err != nil || !ok || took.Number != 3 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
}
