package issues

import (
	"fmt"
	"math"
	"sort"
	"strings"
	"time"
)

// PaceWindow is the built-in value of issues/config/pace_window: how far
// back se issue tree and the briefing measure the fleet's pace.
const PaceWindow = 7 * 24 * time.Hour

// Pace is what the fleet measured over a recent window, read as the retro
// reads it: the closed se issues with the PR that fixed each, and each one's
// claim-to-merge time from its landing answers.
type Pace struct {
	Since time.Time `json:"since"`
	Until time.Time `json:"until"`
	// Merged counts the se issues closed in the window by a merged PR;
	// PerHour is Merged over the window's hours.
	Merged  int     `json:"merged"`
	PerHour float64 `json:"per_hour"`
	// Measured counts those with a claim time; P50 and P90 are their
	// claim-to-merge minutes.
	Measured int `json:"measured"`
	P50      int `json:"p50_minutes"`
	P90      int `json:"p90_minutes"`
}

// Pace measures the fleet over the window that ends now.
func (s Source) Pace(window time.Duration) (Pace, error) {
	until := s.now().UTC().Truncate(time.Second)
	w := RetroWindow{Since: until.Add(-window), Until: until}
	p := Pace{Since: w.Since, Until: until}
	var (
		closed  []past
		fixedBy map[int]merged
	)
	if err := parallel([]func() error{
		func() (err error) { closed, err = s.closedIn(w, 0); return err },
		func() (err error) { _, _, fixedBy, err = s.merges(w); return err },
	}); err != nil {
		return Pace{}, err
	}
	rows := make([]Row, len(closed))
	var reads []func() error
	for k, x := range closed {
		if _, ok := fixedBy[x.Number]; !ok {
			continue
		}
		reads = append(reads, func() (err error) { rows[k], _, err = s.row(x, fixedBy); return err })
	}
	if err := parallel(reads); err != nil {
		return Pace{}, err
	}
	var minutes []int
	for _, r := range rows {
		if r.PR == 0 {
			continue
		}
		p.Merged++
		if r.Minutes >= 0 {
			minutes = append(minutes, r.Minutes)
		}
	}
	p.Measured = len(minutes)
	p.P50, p.P90 = percentile(minutes, 0.5), percentile(minutes, 0.9)
	if hours := window.Hours(); hours > 0 {
		p.PerHour = round2(float64(p.Merged) / hours)
	}
	return p, nil
}

// Queue is the open queue, or one tree of it, and when its last issue is
// estimated to close.
type Queue struct {
	// Root is the tree's root; 0 for the whole queue.
	Root int `json:"root,omitempty"`
	// Open counts the work left: every open leaf, and every open review
	// gate (a parent labelled se-review), which is reviewed once its tree is
	// done. InFlight is the claimed leaves among them.
	Open     int   `json:"open"`
	InFlight []int `json:"in_flight"`
	// Stuck is the leaves in flight that are stuck past the lease: they do
	// not count as running.
	Stuck []int `json:"stuck"`
	Pace  Pace  `json:"pace"`
	// Parallel is how many run at once: the leaves in flight now that are
	// not stuck, or, where the measured pace says more, its merges an hour
	// times its p50 hours; at least one.
	Parallel float64 `json:"parallel"`
	// PaceHours is how long the open work takes at the window's merges an
	// hour, idle hours and all: what the queue takes if the fleet runs as
	// it ran.
	PaceHours float64 `json:"pace_hours,omitempty"`
	// Critical is the longest chain of work that must run one after
	// another, by blocked-by links (an ancestor's count) and review gates
	// after their trees, first to last.
	Critical []int `json:"critical_path"`
	// P50Hours and P90Hours are the estimate, from now until the last issue
	// closes: the larger of the critical path run end to end and the open
	// work spread over Parallel, at the p50 and at the p90 time each. P50At
	// and P90At are when; both are absent with no estimate.
	P50Hours float64    `json:"p50_hours"`
	P90Hours float64    `json:"p90_hours"`
	P50At    *time.Time `json:"p50_at,omitempty"`
	P90At    *time.Time `json:"p90_at,omitempty"`
	// Why says why there is no estimate; empty where there is one.
	Why string `json:"why,omitempty"`
}

// Queue reads the open queue, or root's tree where root is above zero, with
// where each open issue stands, and estimates when the last one closes from
// the pace measured over window.
func (s Source) Queue(root int, window time.Duration) (Queue, []Node, error) {
	var (
		all  []Status
		t    tree
		pace Pace
	)
	if err := parallel([]func() error{
		func() (err error) { all, t, err = s.survey(); return err },
		func() (err error) { pace, err = s.Pace(window); return err },
	}); err != nil {
		return Queue{}, nil, err
	}
	return estimate(all, t, root, pace, s.now()), openNodes(all, t, root), nil
}

// openNodes lists the open issues inside root's tree (all, for 0), each
// after its parent and saying where it stands.
func openNodes(all []Status, t tree, root int) []Node {
	why := map[int]string{}
	for _, st := range all {
		why[st.Number] = st.Why
		if st.Ready() {
			why[st.Number] = "ready"
		}
	}
	out := []Node{}
	var add func(n, depth int)
	add = func(n, depth int) {
		node := nodeOf(t.byNum[n], depth)
		node.Why = why[n]
		out = append(out, node)
		for _, c := range t.subs[n] {
			if _, ok := why[c.Number]; ok {
				add(c.Number, depth+1)
			}
		}
	}
	if root > 0 {
		if _, ok := why[root]; ok {
			add(root, 0)
		}
		return out
	}
	for _, st := range all {
		if st.Above == 0 {
			add(st.Number, 0)
		}
	}
	return out
}

// estimate judges the queue: the work items inside root's tree (all, for 0),
// their critical path, and the time to finish them at the measured pace.
func estimate(all []Status, t tree, root int, pace Pace, now time.Time) Queue {
	q := Queue{Root: root, InFlight: []int{}, Stuck: []int{}, Critical: []int{}, Pace: pace}
	byNum := map[int]Status{}
	for _, st := range all {
		byNum[st.Number] = st
	}
	// inside lists n and every open issue below it.
	var inside func(n int) []int
	inside = func(n int) []int {
		out := []int{n}
		for _, c := range t.subs[n] {
			if _, ok := byNum[c.Number]; ok {
				out = append(out, inside(c.Number)...)
			}
		}
		return out
	}
	review := func(n int) bool { return t.byNum[n].labelled(ReviewLabel) }
	item := func(n int) bool { st, ok := byNum[n]; return ok && (!st.Parent || review(n)) }
	scope := map[int]bool{}
	if root > 0 {
		if _, ok := byNum[root]; ok {
			for _, n := range inside(root) {
				scope[n] = true
			}
		}
	} else {
		for n := range byNum {
			scope[n] = true
		}
	}
	var items []int
	for _, st := range all {
		if scope[st.Number] && item(st.Number) {
			items = append(items, st.Number)
			if st.claimed {
				q.InFlight = append(q.InFlight, st.Number)
			}
			if st.claimed && st.Stuck {
				q.Stuck = append(q.Stuck, st.Number)
			}
		}
	}
	q.Open = len(items)
	// work lists the items a blocker on n waits for: n itself, or every item
	// in its tree.
	work := func(n int) []int {
		var out []int
		for _, m := range inside(n) {
			if scope[m] && item(m) {
				out = append(out, m)
			}
		}
		return out
	}
	deps := map[int][]int{}
	for _, n := range items {
		seen := map[int]bool{}
		add := func(ms []int) {
			for _, m := range ms {
				if m != n && !seen[m] {
					seen[m] = true
					deps[n] = append(deps[n], m)
				}
			}
		}
		for m, ok := n, true; ok; m, ok = t.above[m] {
			for _, b := range t.openBlockers(m) {
				add(work(b))
			}
		}
		if byNum[n].Parent {
			add(work(n))
		}
		sort.Ints(deps[n])
	}
	// chain is the length of the longest run of items ending at n, and next
	// the item before n on it; a cycle of links counts once.
	chain, before, busy := map[int]int{}, map[int]int{}, map[int]bool{}
	var length func(n int) int
	length = func(n int) int {
		if l, ok := chain[n]; ok {
			return l
		}
		if busy[n] {
			return 0
		}
		busy[n] = true
		best := 0
		for _, d := range deps[n] {
			if l := length(d); l > best {
				best, before[n] = l, d
			}
		}
		busy[n] = false
		chain[n] = best + 1
		return best + 1
	}
	last, longest := 0, 0
	for _, n := range items {
		if l := length(n); l > longest {
			last, longest = n, l
		}
	}
	for n, ok := last, last != 0; ok; n, ok = before[n] {
		q.Critical = append([]int{n}, q.Critical...)
	}
	switch {
	case q.Open == 0 && root > 0:
		q.Why = fmt.Sprintf("#%d's tree holds no open work", root)
		return q
	case q.Open == 0:
		q.Why = "the queue is empty"
		return q
	case pace.Measured == 0:
		q.Why = fmt.Sprintf("no se issue merged with a claim time since %s", pace.Since.Format(time.RFC3339))
		return q
	}
	q.Parallel = math.Max(1, math.Max(float64(len(q.InFlight)-len(q.Stuck)), round2(pace.PerHour*float64(pace.P50)/60)))
	if pace.Merged > 0 {
		q.PaceHours = round2(float64(q.Open) * pace.Until.Sub(pace.Since).Hours() / float64(pace.Merged))
	}
	hours := func(minutes int) float64 {
		path := float64(len(q.Critical) * minutes)
		wide := float64(q.Open*minutes) / q.Parallel
		return round2(math.Max(path, wide) / 60)
	}
	q.P50Hours, q.P90Hours = hours(pace.P50), hours(pace.P90)
	p50 := now.UTC().Add(time.Duration(q.P50Hours * float64(time.Hour))).Truncate(time.Minute)
	p90 := now.UTC().Add(time.Duration(q.P90Hours * float64(time.Hour))).Truncate(time.Minute)
	q.P50At, q.P90At = &p50, &p90
	return q
}

// Span says a number of minutes the way a person reads it: 45m, 3.5h, 2.1d.
func Span(minutes float64) string {
	switch {
	case minutes < 60:
		return fmt.Sprintf("%.0fm", minutes)
	case minutes < 48*60:
		return strings.TrimSuffix(fmt.Sprintf("%.1f", minutes/60), ".0") + "h"
	}
	return strings.TrimSuffix(fmt.Sprintf("%.1f", minutes/60/24), ".0") + "d"
}

// Chain names a chain of issues: #1 → #2 → #3.
func Chain(ns []int) string {
	names := make([]string, len(ns))
	for k, n := range ns {
		names[k] = fmt.Sprintf("#%d", n)
	}
	return strings.Join(names, " → ")
}

// Line says the estimate in one sentence: the work left and when it is done.
func (q Queue) Line() string {
	head := fmt.Sprintf("%d open, %d in flight", q.Open, len(q.InFlight))
	if q.Why != "" {
		return head + "; no estimate: " + q.Why + "."
	}
	return fmt.Sprintf("%s; the last closes in %s (p50) to %s (p90), by %s to %s.", head,
		Span(q.P50Hours*60), Span(q.P90Hours*60), q.P50At.Format("2006-01-02 15:04Z"), q.P90At.Format("2006-01-02 15:04Z"))
}

// Text is the estimate and how it was made, a few lines.
func (q Queue) Text() string {
	lines := []string{"Estimate: " + q.Line()}
	if len(q.InFlight) > 0 {
		stuck := ""
		if len(q.Stuck) > 0 {
			stuck = fmt.Sprintf("; stuck, not counted as running: %s", strings.ReplaceAll(Chain(q.Stuck), " → ", ", "))
		}
		lines = append(lines, "In flight: "+strings.ReplaceAll(Chain(q.InFlight), " → ", ", ")+stuck+".")
	}
	p := q.Pace
	took := "no claim-to-merge time measured"
	if p.Measured > 0 {
		took = fmt.Sprintf("claim to merge %s (p50) to %s (p90), of %d measured", Span(float64(p.P50)), Span(float64(p.P90)), p.Measured)
	}
	lines = append(lines, fmt.Sprintf("Pace since %s (%s, PaceWindow): %d merged, %.2f an hour; %s.",
		p.Since.Format("2006-01-02 15:04Z"), Span(p.Until.Sub(p.Since).Minutes()), p.Merged, p.PerHour, took))
	if q.Why == "" {
		lines = append(lines, fmt.Sprintf("Parallel: %s at once.", strings.TrimSuffix(fmt.Sprintf("%.1f", q.Parallel), ".0")))
	}
	if q.PaceHours > 0 {
		lines = append(lines, fmt.Sprintf("At the window's pace, idle hours and all, the %d take %s.", q.Open, Span(q.PaceHours*60)))
	}
	if len(q.Critical) > 0 {
		lines = append(lines, fmt.Sprintf("Critical path, %d in a row: %s.", len(q.Critical), Chain(q.Critical)))
	}
	return strings.Join(lines, "\n")
}
