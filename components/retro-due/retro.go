// Package retrodue is SE's retro-due component: how many work issues landed
// since the last retro (scripts/retro.py landed_since_retro) and whether
// that makes a retro due, and how many retros closed since the last overhaul
// (scripts/overhaul.py retros_since_overhaul) and whether that makes an
// overhaul due, as a derivation over kern's GitHub snapshot names, so the
// greeting reads both live. It is SE's, not kern's: the windows and what
// counts are SE's work model.
package retrodue

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/kern/index"
	"github.com/mb-89/se/components/snap"
)

// Name is the component's name, which the wiring's instances name.
const Name = "retro-due"

// SE's marks, as retro.py names them.
const (
	Label     = "retro"
	TitleStem = "docs/retro-"
	Work      = "work"
	// OverhaulTitleStem is overhaul.py OVERHAUL_TITLE.
	OverhaulTitleStem = "docs/overhaul-"
)

var reference = regexp.MustCompile(`(?i)\b(?:fixes|refs|closes)\s+(?:#(\d+)|https://[^/\s]+/([^/\s]+/[^/\s]+)/issues/(\d+))\b`)

// Due is the component's output: the work issues landed since the last retro,
// the count that makes a retro due and whether it is, where the window starts
// (the last retro's close, or the oldest open retro's creation, or none: the
// whole history); the same countdown for the overhaul, counting the retros
// closed since the last overhaul; and how much the names held.
type Due struct {
	Landed        int    `json:"landed"`
	DueAfter      int    `json:"due_after"`
	Due           bool   `json:"due"`
	Since         string `json:"since"`
	Retro         int    `json:"retro"`
	Retros        int    `json:"retros"`
	OverhaulAfter int    `json:"overhaul_after"`
	OverhaulDue   bool   `json:"overhaul_due"`
	OverhaulSince string `json:"overhaul_since"`
	Overhaul      int    `json:"overhaul"`
	Issues        int    `json:"issues"`
	Pulls         int    `json:"pulls"`
}

// In is what the derivation reads.
type In struct {
	Issues        map[string]github.Snapshot `index:"issues"`
	Pulls         map[string]github.Snapshot `index:"pulls"`
	DueAfter      int                        `index:"config/due-after"`
	OverhaulAfter int                        `index:"config/overhaul-after"`
	Tracker       string                     `index:"config/tracker"`
	Base          string                     `index:"config/base"`
}

// Component is the component a binary carries.
var Component = index.Declare(Name, "Whether a retro or an overhaul is due: the work issues landed since the last retro and the retros closed since the last overhaul, from the GitHub names.",
	index.Config("due-after", 10, "How many landed work issues make a retro due: se.toml [retro] due_after."),
	index.Config("overhaul-after", 3, "How many closed retros make an overhaul due: se.toml [overhaul] due_after."),
	index.Config("tracker", "", "The tracker, <owner>/<repo>: a pull request's Fixes or Refs URL names an issue only there."),
	index.Config("base", "main", "The integration branch: a work issue landed where a pull request naming it merged into it."),
	index.Derived("due", Due{DueAfter: 10, OverhaulAfter: 3}, "The work issues landed since the last retro and whether a retro is due; the retros closed since the last overhaul and whether an overhaul is due.",
		func(in In) (Due, error) { return Count(in), nil }),
)

func init() { index.Register(Component) }

func isRetro(i snap.Issue) bool { return strings.HasPrefix(i.Title, TitleStem) || i.Has(Label) }

func isOverhaul(i snap.Issue) bool { return strings.HasPrefix(i.Title, OverhaulTitleStem) }

func isDuplicate(i snap.Issue) bool { return i.Reason == "duplicate" || i.Has("duplicate") }

// windowStart is where a countdown of the runs `of` picks out starts: the
// close of the last closed one, else the creation of the oldest open one,
// else nowhere (ok false: the whole history); with the moment as the names
// give it and that run's number.
func windowStart(all []snap.Issue, of func(snap.Issue) bool) (since time.Time, ok bool, at string, number int) {
	var last *snap.Issue
	for i := range all {
		c, closed := snap.When(all[i].ClosedAt)
		if all[i].State == "closed" && of(all[i]) && closed && (last == nil || c.After(since)) {
			last, since = &all[i], c
		}
	}
	if last != nil {
		return since, true, last.ClosedAt, last.Number
	}
	var oldest *snap.Issue
	for i := range all {
		c, created := snap.When(all[i].CreatedAt)
		if all[i].State == "open" && of(all[i]) && created && (oldest == nil || c.Before(since)) {
			oldest, since = &all[i], c
		}
	}
	if oldest != nil {
		return since, true, oldest.CreatedAt, oldest.Number
	}
	return time.Time{}, false, "", 0
}

// Count is retro.py landed_since_retro and overhaul.py retros_since_overhaul
// over what the names hold.
func Count(in In) Due {
	all := snap.Issues(in.Issues)
	pulls := snap.Pulls(in.Pulls)
	d := Due{DueAfter: in.DueAfter, OverhaulAfter: in.OverhaulAfter, Issues: len(all), Pulls: len(pulls)}
	since, hasSince, at, number := windowStart(all, isRetro)
	d.Since, d.Retro = at, number
	overhaulSince, hasOverhaulSince, at, number := windowStart(all, isOverhaul)
	d.OverhaulSince, d.Overhaul = at, number
	for _, i := range all {
		closedAt, ok := snap.When(i.ClosedAt)
		if i.State == "closed" && isRetro(i) && ok && (!hasOverhaulSince || closedAt.After(overhaulSince)) &&
			!isDuplicate(i) && i.Reason != "not_planned" {
			d.Retros++
		}
	}
	naming := map[int][]snap.Pull{}
	for _, p := range pulls {
		if n, ok := Reference(p.Body, in.Tracker); ok {
			naming[n] = append(naming[n], p)
		}
	}
	for _, i := range all {
		closedAt, ok := snap.When(i.ClosedAt)
		if i.State != "closed" || !i.Has(Work) || isRetro(i) || !ok || (hasSince && !closedAt.After(since)) {
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
		}
	}
	d.Due = d.DueAfter > 0 && d.Landed >= d.DueAfter
	d.OverhaulDue = d.OverhaulAfter > 0 && d.Retros >= d.OverhaulAfter
	return d
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
