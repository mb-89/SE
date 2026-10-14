package issues

import (
	"errors"
	"fmt"
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/mb-89/SE/src/modules/io/github"
	sehttp "github.com/mb-89/SE/src/modules/io/http"
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
	got, _, err := s.fleet(all, pulls)
	return got, err
}

// kept is a fan-out the routine refused for its fire rate limit, kept in
// the alive claims' comments until it fires: at is the latest retry time a
// claim records, on the claims that record one.
type kept struct {
	at time.Time
	on []int
}

// due says whether the refused fan-out may fire at now: none waits, or its
// retry time has come.
func (p kept) due(now time.Time) bool { return p.at.IsZero() || !now.Before(p.at) }

// fleet is boxes, with the refused fan-out the alive claims record.
func (s Source) fleet(all []Status, pulls []openPull) (map[string]int, kept, error) {
	// A claimed tree runs no sub-agent of its own, but its claim keeps a
	// refused fan-out as a leaf's does: boxes take only manifests.
	var alive []int
	trees := map[int]bool{}
	for _, st := range all {
		if st.claimed && !st.Stuck && !st.Parent || st.staked {
			alive = append(alive, st.Number)
			trees[st.Number] = st.staked
		}
	}
	ms, err := each(len(alive), func(k int) (marks, error) { return s.marks(alive[k]) })
	if err != nil {
		return nil, kept{}, err
	}
	up := toMain(pulls)
	out := map[string]int{}
	var p kept
	for k, m := range ms {
		switch {
		case trees[alive[k]]:
		case m.box == "":
			out[fmt.Sprintf("#%d", alive[k])] = s.parallel()
		case up[Branch(alive[k])].AutoMerge != nil:
			out[m.box] += 0
		default:
			out[m.box]++
		}
		if !m.retry.IsZero() {
			p.on = append(p.on, alive[k])
			if m.retry.After(p.at) {
				p.at = m.retry
			}
		}
	}
	return out, p, nil
}

// fanoutMark records a fan-out the routine refused for its rate limit on the
// claim whose take it followed, <!-- se:fanout-retry 2026-10-14T10:00:00Z -->
// naming when it may fire, and <!-- se:fanout-fired --> that it fired.
var fanoutMark = regexp.MustCompile(`<!-- se:fanout-(retry|fired)(?: (\S+))? -->`)

// RetryWait is how long a 429 that names no Retry-After keeps the fan-out:
// the routine's limit is counted by the hour.
const RetryWait = time.Hour

// retryNote is the comment that keeps a refused fan-out until at.
func retryNote(at time.Time) string {
	return fmt.Sprintf("The routine refused the fan-out for its fire rate limit until %s; the next take or se fleet check after then fires it.\n<!-- se:fanout-retry %s -->", at.Format(time.RFC3339), at.Format(time.RFC3339))
}

// keep records on issue n's comments that the fan-out waits until at.
func (s Source) keep(n int, at time.Time) error {
	_, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n), github.F("body", retryNote(at)))
	return err
}

// shoot fires once and keeps the books on the refused fan-out p: every claim
// that records it is told it fired, and a fire the routine refuses for its
// rate limit is kept on issue at (where at is not zero) with its retry time.
func (s Source) shoot(fire func() Shot, at int, p kept) string {
	shot := fire()
	line := shot.Line
	var errs []string
	for _, n := range p.on {
		if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n), github.F("body", "The fan-out the routine refused fired again.\n<!-- se:fanout-fired -->")); err != nil {
			errs = append(errs, fmt.Sprintf("#%d: %v", n, err))
		}
	}
	if shot.Limited && at != 0 {
		when := sehttp.RetryAt(s.now(), shot.RetryAfter)
		if when.IsZero() {
			when = s.now().Add(RetryWait)
		}
		if err := s.keep(at, when); err != nil {
			errs = append(errs, fmt.Sprintf("#%d: %v", at, err))
		} else {
			line += fmt.Sprintf(" Kept on #%d: the next take or se fleet check after %s fires it.", at, when.Format(time.RFC3339))
		}
	}
	if len(errs) > 0 {
		line += " (the refused fan-out's record could not be written: " + strings.Join(errs, "; ") + ")"
	}
	return line
}

// waitsLine is the line of a take that finds the refused fan-out p not due yet.
func waitsLine(p kept) string {
	return fmt.Sprintf("Fan-out waits: the routine refused the fan-out after #%d until %s, so nothing fires before; the next take or se fleet check after then fires it.", p.on[len(p.on)-1], p.at.Format(time.RFC3339))
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
// answers one line saying what it did: after the take of claim, or the
// creation of a ready issue (claim zero). It fires where issues are ready and
// no box is alive, or where every alive box runs its cap and another issue is
// ready. While a box has room under its cap, that box takes the issue itself,
// and nothing fires. A taking box with a session counts as alive. fire is the
// fire itself; a read that fails fires, so no ready issue waits on it.
//
// A fire the routine refuses for its rate limit is kept on the claim with
// the retry time its 429 names (RetryWait where it names none). Until that
// time nothing fires, and a take keeps it on its own claim too, so it outlives
// the claim that first kept it; once it has passed, the next fire the fleet
// needs, here or in se fleet check, is that kept one.
func (s Source) FanOut(fire func() Shot, claim int) string {
	taking := claim != 0
	all, t, err := s.survey()
	if err != nil {
		return s.shoot(fire, claim, kept{}) + fmt.Sprintf(" (the boxes could not be counted: %v)", err)
	}
	ready := len(takeOrder(all, 0)) > 0
	got, p, err := s.fleet(all, t.pulls)
	if err != nil {
		return s.shoot(fire, claim, kept{}) + fmt.Sprintf(" (the boxes could not be counted: %v)", err)
	}
	if _, ok := got[s.Box]; taking && s.Box != "" && !ok {
		got[s.Box] = 0
	}
	if ready && !p.due(s.now()) {
		line := waitsLine(p)
		if taking && !slices.Contains(p.on, claim) {
			if err := s.keep(claim, p.at); err != nil {
				line += fmt.Sprintf(" (it could not be kept on #%d: %v)", claim, err)
			}
		}
		return line
	}
	return fanOut(got, s.parallel(), ready, func() string { return s.shoot(fire, claim, p) })
}

// retryFanOut is se fleet check's part in the fan-out, on a survey already
// read: where the alive claims keep a refused fan-out, it fires it once its
// retry time has passed and the fleet still needs the box (as FanOut judges),
// and answers what it did. Where none is kept, it reads nothing more and
// answers nothing.
func (s Source) retryFanOut(all []Status, t tree, fire func() Shot) string {
	got, p, err := s.fleet(all, t.pulls)
	if err != nil {
		return fmt.Sprintf("Fan-out: the refused fan-out could not be read: %v", err)
	}
	if len(p.on) == 0 {
		return ""
	}
	if !p.due(s.now()) {
		return waitsLine(p)
	}
	return fanOut(got, s.parallel(), len(takeOrder(all, 0)) > 0, func() string { return s.shoot(fire, p.on[len(p.on)-1], p) })
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
