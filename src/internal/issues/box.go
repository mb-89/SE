package issues

import (
	"errors"
	"fmt"
	"regexp"
	"sort"

	"github.com/mb-89/SE/src/internal/io/github"
)

// Parallel is the built-in value of fleet.box/config/parallel: how many
// sub-agents one box runs at once. The box's disk allowance and CPU limit it,
// and the battery takes about 25s.
const Parallel = 4

// boxMark records on an issue the box whose claim it is: <!-- se:box ID -->,
// ID the box's session. The last one on an issue names its box.
var boxMark = regexp.MustCompile(`<!-- se:box (\S+) -->`)

// boxNote is the comment, or the part of one, that records a claim's box.
func (s Source) boxNote() string {
	return fmt.Sprintf("Claimed by the box in session %s.\n<!-- se:box %s -->", s.Box, s.Box)
}

// boxLine is the box note a takeover's comment ends in, where s names a box.
func (s Source) boxLine() string {
	if s.Box == "" {
		return ""
	}
	return "\n\n" + s.boxNote()
}

// markBox records on issue n that s.Box claimed it, where s names a box.
func (s Source) markBox(n int) error {
	if s.Box == "" {
		return nil
	}
	_, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n), github.F("body", s.boxNote()))
	return err
}

// parallel is the cap s runs under: Parallel unless set.
func (s Source) parallel() int {
	if s.Parallel > 0 {
		return s.Parallel
	}
	return Parallel
}

// Full is a box's take refused because the box runs its cap of sub-agents.
type Full struct {
	Box               string
	Running, Parallel int
}

func (f Full) Error() string {
	return fmt.Sprintf("this box runs %d of its %d sub-agents: pull again when one lands", f.Running, f.Parallel)
}

// IsFull says whether err is a take refused for a full box.
func IsFull(err error) bool {
	var f Full
	return errors.As(err, &f)
}

// surveyed is the statuses a survey judged, with what it read.
type surveyed struct {
	all []Status
	t   tree
}

// boxes counts the sub-agents each alive box runs, from the claims in all: a
// claimed leaf whose lease has not run out is alive, and its last box mark
// names its box. Its sub-agent runs until its PR into main, among pulls, has
// auto-merge on; the box stays alive with it. A claim without a mark was made
// by a box that coordinates nothing (an older one, or one with no session):
// it counts as a box of its own, at its cap.
func (s Source) boxes(all []Status, pulls []openPull) (map[string]int, error) {
	var alive []int
	for _, st := range all {
		if st.claimed && !st.Stuck && !st.Parent {
			alive = append(alive, st.Number)
		}
	}
	ids, err := each(len(alive), func(k int) (string, error) {
		m, err := s.marks(alive[k])
		return m.box, err
	})
	if err != nil {
		return nil, err
	}
	up := toMain(pulls)
	out := map[string]int{}
	for k, id := range ids {
		switch {
		case id == "":
			out[fmt.Sprintf("#%d", alive[k])] = s.parallel()
		case up[Branch(alive[k])].AutoMerge != nil:
			out[id] += 0
		default:
			out[id]++
		}
	}
	return out, nil
}

// room refuses a take for s.Box where it already runs its cap.
func (s Source) room(all []Status, pulls []openPull) error {
	if s.Box == "" {
		return nil
	}
	got, err := s.boxes(all, pulls)
	if err != nil {
		return err
	}
	if got[s.Box] >= s.parallel() {
		return Full{Box: s.Box, Running: got[s.Box], Parallel: s.parallel()}
	}
	return nil
}

// FanOut fires the routine once where the fleet needs another box, and
// answers one line saying what it did: after a take (taking set) or the
// creation of a ready issue. It fires where issues are ready and no box is
// alive, or where every alive box runs its cap and another issue is ready.
// While a box has room under its cap, that box takes the issue itself, and
// nothing fires. A taking box with a session counts as alive. fire is the
// fire itself; a read that fails fires, so no ready issue waits on it.
func (s Source) FanOut(fire func() string, taking bool) string {
	all, t, err := s.survey()
	if err != nil {
		return fire() + fmt.Sprintf(" (the boxes could not be counted: %v)", err)
	}
	ready := len(takeOrder(all, 0)) > 0
	got, err := s.boxes(all, t.pulls)
	if err != nil {
		return fire() + fmt.Sprintf(" (the boxes could not be counted: %v)", err)
	}
	if _, ok := got[s.Box]; taking && s.Box != "" && !ok {
		got[s.Box] = 0
	}
	return fanOut(got, s.parallel(), ready, fire)
}

// fanOut decides on the boxes counted: alive boxes and their claims.
func fanOut(got map[string]int, parallel int, ready bool, fire func() string) string {
	if !ready {
		return "Fan-out: no other issue is ready, so nothing fires."
	}
	if len(got) == 0 {
		return fire()
	}
	var ids []string
	for id := range got {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		if got[id] < parallel {
			return fmt.Sprintf("Fan-out: the box in session %s runs %d of its %d sub-agents and takes the next issue itself, so nothing fires.", id, got[id], parallel)
		}
	}
	return fire()
}
