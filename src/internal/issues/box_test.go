// Internal test package: it drives fanOut and the box count, unexported.
package issues

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/github"
)

// fired counts the fires a fan-out made.
type fired int

func (f *fired) fire() string { *f++; return "fired" }

// shot is fire as FanOut takes it: a fire the routine took.
func (f *fired) shot() Shot { *f++; return Shot{Line: "fired"} }

// limited is a fire the routine refused for its rate limit, naming after.
func (f *fired) limited(after string) func() Shot {
	return func() Shot {
		*f++
		return Shot{Line: "Fan-out refused: 429 Too Many Requests", Limited: true, RetryAfter: after}
	}
}

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
	if note := s.FanOut(f.shot, 0); f != 1 || note != "fired" {
		t.Fatalf("%d fires: %q", f, note)
	}
	// A box that takes counts as alive with room.
	s.Box = "s3"
	if note := s.FanOut(f.shot, 5); f != 1 || !strings.Contains(note, "s3 runs 0 of its 2") {
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

func TestARefusedFanOutIsKeptAndFiresOnceItsRetryTimeHasPassed(t *testing.T) {
	t.Parallel()
	g := newHub(t, pushedAt(unblocked(map[string]string{
		listPath: list(node(1, 0), node(2, 0), node(3, 0), node(4, 0)),
		refsPath: refs(1, 2),
	}, 4), fresh, 1, 2))
	g.say(1, (Source{Box: "s1"}).boxNote())
	g.say(2, (Source{Box: "s1"}).boxNote())
	clk := atNow()
	s := g.source()
	s.Box, s.Parallel, s.Clock = "s1", 2, clk
	var f fired
	// s1 runs its cap after taking #2, and #3 is ready: the fire is refused
	// with 429, and kept on #2 until the time it names.
	note := s.FanOut(f.limited("1800"), 2)
	at := now.Add(30 * time.Minute).Format(time.RFC3339)
	if f != 1 || !strings.Contains(note, "Kept on #2") || !strings.Contains(note, at) {
		t.Fatalf("%d fires: %q", f, note)
	}
	if last := g.comments(2); !strings.Contains(last[len(last)-1].Body, "<!-- se:fanout-retry "+at+" -->") {
		t.Fatalf("%+v", last)
	}
	// The next take before that time fires nothing, and keeps it on its own
	// claim too, so it outlives #2.
	if note := s.FanOut(f.shot, 1); f != 1 || !strings.HasPrefix(note, "Fan-out waits") || !strings.Contains(note, at) {
		t.Fatalf("%d fires: %q", f, note)
	}
	if last := g.comments(1); !strings.Contains(last[len(last)-1].Body, "<!-- se:fanout-retry "+at+" -->") {
		t.Fatalf("%+v", last)
	}
	// se fleet check before the time fires nothing either.
	if _, note, err := s.CheckFanOut(f.shot); err != nil || f != 1 || !strings.HasPrefix(note, "Fan-out waits") {
		t.Fatalf("%d fires: %q %v", f, note, err)
	}
	// Once it has passed, se fleet check fires it, once: every claim that
	// kept it is told.
	clk.Advance(31 * time.Minute)
	if _, note, err := s.CheckFanOut(f.shot); err != nil || f != 2 || note != "fired" {
		t.Fatalf("%d fires: %q %v", f, note, err)
	}
	for _, n := range []int{1, 2} {
		if last := g.comments(n); !strings.Contains(last[len(last)-1].Body, "<!-- se:fanout-fired -->") {
			t.Fatalf("#%d: %+v", n, last)
		}
	}
	if _, note, err := s.CheckFanOut(f.shot); err != nil || f != 2 || note != "" {
		t.Fatalf("%d fires: %q %v", f, note, err)
	}
	// A 429 that names no retry keeps the fan-out RetryWait; the take once
	// it has passed fires it.
	if note := s.FanOut(f.limited(""), 2); f != 3 || !strings.Contains(note, clk.Now().Add(RetryWait).Format(time.RFC3339)) {
		t.Fatalf("%d fires: %q", f, note)
	}
	clk.Advance(RetryWait)
	if note := s.FanOut(f.shot, 2); f != 4 || note != "fired" {
		t.Fatalf("%d fires: %q", f, note)
	}
	if _, p, err := s.fleet(mustSurvey(t, s), nil); err != nil || len(p.on) != 0 {
		t.Fatalf("%+v %v", p, err)
	}
}

func mustSurvey(t *testing.T, s Source) []Status {
	t.Helper()
	all, err := s.Survey()
	if err != nil {
		t.Fatal(err)
	}
	return all
}
