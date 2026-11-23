// Package retrodue is SE's retro-due component: what came back since the
// newest retro started (scripts/retro.py retro_countdown) and whether that
// makes a retro due, and how many retros closed since the newest overhaul
// started (scripts/overhaul.py overhaul_countdown) and whether that makes an
// overhaul due, as a derivation over kern's GitHub snapshot names, so the
// greeting reads both live. It is SE's, not kern's: the windows and what
// counts are SE's work model.
package retrodue

import (
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"kern/components/github"
	"kern/index"
	"se/components/snap"
)

// Name is the component's name, which the wiring's instances name.
const Name = "retro-due"

// SE's marks, as retro.py names them.
const (
	Label     = "retro"
	TitleStem = "docs/retro-"
	Work      = "work"
	Escalated = "escalated"
)

// overhaulName is overhaul.py OVERHAUL_NAME: `overhaul-<yyyymmdd>`, or, filed before the name
// rule, `docs/overhaul-<yyyymmdd>`.
var overhaulName = regexp.MustCompile(`^(?:docs/)?overhaul-\d{8}$`)

var reference = regexp.MustCompile(`(?i)\b(?:fixes|refs|closes)\s+(?:#(\d+)|https://[^/\s]+/([^/\s]+/[^/\s]+)/issues/(\d+))\b`)

// Now is the clock the day rules count on; a test replaces it.
var Now = time.Now

// Due is the component's output (scripts/retro.py retro_countdown and
// scripts/overhaul.py overhaul_countdown): what came back since the newest
// retro started (its creation), weighted into Count (a landing 1, an
// escalated work issue FailureWeight), whether that or Days days since that
// start make a retro due and why, and the retros still open; the same for the
// overhaul, counting the retros closed since the newest overhaul started; and
// how much the names held.
type Due struct {
	Landed         int    `json:"landed"`
	Failed         int    `json:"failed"`
	Count          int    `json:"count"`
	DueAfter       int    `json:"due_after"`
	FailureWeight  int    `json:"failure_weight"`
	Days           int    `json:"days"`
	Due            bool   `json:"due"`
	Reason         string `json:"reason"`
	Open           []int  `json:"open"`
	Since          string `json:"since"`
	Retro          int    `json:"retro"`
	Retros         int    `json:"retros"`
	OverhaulAfter  int    `json:"overhaul_after"`
	OverhaulDays   int    `json:"overhaul_days"`
	OverhaulDue    bool   `json:"overhaul_due"`
	OverhaulReason string `json:"overhaul_reason"`
	OverhaulOpen   []int  `json:"overhaul_open"`
	OverhaulSince  string `json:"overhaul_since"`
	Overhaul       int    `json:"overhaul"`
	Issues         int    `json:"issues"`
	Pulls          int    `json:"pulls"`
}

// In is what the derivation reads.
type In struct {
	Issues        map[string]github.Snapshot `index:"issues"`
	Pulls         map[string]github.Snapshot `index:"pulls"`
	DueAfter      int                        `index:"config/due-after"`
	FailureWeight int                        `index:"config/failure-weight"`
	Days          int                        `index:"config/days"`
	OverhaulAfter int                        `index:"config/overhaul-after"`
	OverhaulDays  int                        `index:"config/overhaul-days"`
	Tracker       string                     `index:"tracker"`
	Base          string                     `index:"config/base"`
}

// Component is the component a binary carries.
var Component = index.Declare(Name, "Whether a retro or an overhaul is due or open: what came back since the newest retro started and the retros closed since the newest overhaul started, from the GitHub names.",
	index.Config("due-after", 20, "How much that came back makes a retro due, a landing 1 and a failure failure-weight: se.toml [retro] due_after."),
	index.Config("failure-weight", 5, "What an escalated work issue adds: se.toml [retro] failure_weight."),
	index.Config("days", 7, "After how many days since the newest retro started, with anything come back, a retro is due; 0 is off: se.toml [retro] days."),
	index.Config("overhaul-after", 3, "How many closed retros make an overhaul due; 0 is off: se.toml [overhaul] due_after."),
	index.Config("overhaul-days", 30, "After how many days since the newest overhaul started, with a retro closed, an overhaul is due; 0 is off: se.toml [overhaul] days."),
	index.Config("base", "main", "The integration branch: a work issue landed where a pull request naming it merged into it."),
	index.Derived("due", Due{DueAfter: 20, FailureWeight: 5, Days: 7, OverhaulAfter: 3, OverhaulDays: 30}, "What came back since the newest retro started and whether a retro is due or open; the retros closed since the newest overhaul started and whether an overhaul is due or open.",
		func(in In) (Due, error) { return Count(in, Now().UTC()), nil }),
)

func init() { index.Register(Component) }

func isRetro(i snap.Issue) bool { return strings.HasPrefix(i.Title, TitleStem) || i.Has(Label) }

func isOverhaul(i snap.Issue) bool { return overhaulName.MatchString(strings.TrimSpace(i.Title)) }

func isDuplicate(i snap.Issue) bool { return i.Reason == "duplicate" || i.Has("duplicate") }

// counted is a run that counts: not closed as a duplicate or not planned
// (retro.py counted_run).
func counted(i snap.Issue) bool { return !isDuplicate(i) && i.Reason != "not_planned" }

// runStart is when a run started: its creation, else its close (retro.py
// run_start), with the moment as the names give it.
func runStart(i snap.Issue) (time.Time, string, bool) {
	if t, ok := snap.When(i.CreatedAt); ok {
		return t, i.CreatedAt, true
	}
	t, ok := snap.When(i.ClosedAt)
	return t, i.ClosedAt, ok
}

// newestStart is where a countdown of the runs `of` picks out starts: the
// start of the newest that counts, open or closed, else nowhere (ok false: the
// whole history); with the moment as the names give it and that run's number.
func newestStart(all []snap.Issue, of func(snap.Issue) bool) (since time.Time, ok bool, at string, number int) {
	for _, i := range all {
		t, given, started := runStart(i)
		if of(i) && counted(i) && started && (!ok || t.After(since)) {
			since, ok, at, number = t, true, given, i.Number
		}
	}
	return since, ok, at, number
}

// opened is the numbers of the open runs `of` picks out, lowest first.
func opened(all []snap.Issue, of func(snap.Issue) bool) []int {
	out := []int{}
	for _, i := range all {
		if i.State == "open" && of(i) {
			out = append(out, i.Number)
		}
	}
	sort.Ints(out)
	return out
}

// elapsedDays is the whole days from start to now, start the given since or,
// with none, the earliest of the moments (retro.py: `(now - start).days`).
func elapsedDays(since time.Time, ok bool, moments []time.Time, now time.Time) int {
	start, have := since, ok
	for _, m := range moments {
		if !have || m.Before(start) {
			start, have = m, true
		}
	}
	if !have {
		return 0
	}
	return int(math.Floor(now.Sub(start).Hours() / 24))
}

// reason is retro.py due_reason: why a countdown is due, or "" where it is
// not.
func reason(kind string, count int, what string, dueAfter, days, elapsed int) string {
	if dueAfter > 0 && count >= dueAfter {
		return fmt.Sprintf("%d %s since the last %s (due at %d)", count, what, kind, dueAfter)
	}
	if days > 0 && count > 0 && elapsed >= days {
		return fmt.Sprintf("%d days since the last %s with %d %s (due after %d days)", elapsed, kind, count, what, days)
	}
	return ""
}

// Count is retro.py retro_countdown and overhaul.py overhaul_countdown over
// what the names hold, at now.
func Count(in In, now time.Time) Due {
	all := snap.Issues(in.Issues)
	pulls := snap.Pulls(in.Pulls)
	d := Due{DueAfter: in.DueAfter, FailureWeight: in.FailureWeight, Days: in.Days,
		OverhaulAfter: in.OverhaulAfter, OverhaulDays: in.OverhaulDays, Issues: len(all), Pulls: len(pulls)}
	since, hasSince, at, number := newestStart(all, isRetro)
	d.Since, d.Retro = at, number
	after := func(value string) (time.Time, bool) {
		t, ok := snap.When(value)
		return t, ok && (!hasSince || t.After(since))
	}
	naming := map[int][]snap.Pull{}
	for _, p := range pulls {
		if n, ok := Reference(p.Body, in.Tracker); ok {
			naming[n] = append(naming[n], p)
		}
	}
	var moments []time.Time
	for _, i := range all {
		closedAt, ok := after(i.ClosedAt)
		if i.State != "closed" || !i.Has(Work) || isRetro(i) || !ok {
			continue
		}
		candidates := naming[i.Number]
		sort.Slice(candidates, func(a, b int) bool { return candidates[a].Number > candidates[b].Number })
		landed := false
		for _, p := range candidates {
			if p.MergedAt != "" && p.Base == in.Base {
				landed = true
				break
			}
		}
		if landed && !isDuplicate(i) && i.Reason != "not_planned" {
			d.Landed++
			moments = append(moments, closedAt)
		}
	}
	for _, i := range all {
		if updated, ok := after(i.UpdatedAt); ok && i.Has(Work) && i.Has(Escalated) && !isRetro(i) {
			d.Failed++
			moments = append(moments, updated)
		}
	}
	d.Count = d.Landed + d.Failed*in.FailureWeight
	d.Reason = reason("retro", d.Count, "came back", in.DueAfter, in.Days, elapsedDays(since, hasSince, moments, now))
	d.Due, d.Open = d.Reason != "", opened(all, isRetro)
	var retros []time.Time
	d.Retros, retros, d.OverhaulSince, d.Overhaul = RetrosSince(all)
	oSince, oOK, _, _ := newestStart(all, isOverhaul)
	d.OverhaulReason = reason("overhaul", d.Retros, "retros closed", in.OverhaulAfter, in.OverhaulDays,
		elapsedDays(oSince, oOK, retros, now))
	d.OverhaulDue, d.OverhaulOpen = d.OverhaulReason != "", opened(all, isOverhaul)
	return d
}

// RetrosSince is the overhaul countdown, a pure function of the runs it is
// given (overhaul.py overhaul_countdown): how many retros closed since the
// newest overhaul started, with their closes, where that window starts and the
// overhaul it starts at. A retro closed as a duplicate or not planned does not
// count. Whether that makes an overhaul due is Count's.
func RetrosSince(all []snap.Issue) (count int, closes []time.Time, since string, overhaul int) {
	at, ok, since, overhaul := newestStart(all, isOverhaul)
	for _, i := range all {
		closedAt, closed := snap.When(i.ClosedAt)
		if i.State == "closed" && isRetro(i) && closed && (!ok || closedAt.After(at)) && counted(i) {
			count++
			closes = append(closes, closedAt)
		}
	}
	return count, closes, since, overhaul
}

// Reference is the issue of tracker a pull request's body first names with
// Fixes, Refs or Closes: retro.py reference.
func Reference(body, tracker string) (int, bool) {
	m := reference.FindStringSubmatch(body)
	if m == nil {
		return 0, false
	}
	if m[1] != "" {
		n, _ := strconv.Atoi(m[1])
		return n, true
	}
	parts := strings.Split(tracker, "/")
	if len(parts) > 2 {
		parts = parts[len(parts)-2:]
	}
	if !strings.EqualFold(m[2], strings.Join(parts, "/")) {
		return 0, false
	}
	n, _ := strconv.Atoi(m[3])
	return n, true
}
