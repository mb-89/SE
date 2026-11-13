// Package retro is SE's retro-due component: how many work issues landed
// since the last retro (scripts/retro.py landed_since_retro) and whether
// that makes a retro due, as a derivation over kern's GitHub snapshot names,
// so the greeting reads it live. It is SE's, not kern's: the window and what
// counts as landed are SE's work model.
package retro

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
const Name = "retro"

// SE's marks, as retro.py names them.
const (
	Label     = "retro"
	TitleStem = "docs/retro-"
	Work      = "work"
)

var reference = regexp.MustCompile(`(?i)\b(?:fixes|refs|closes)\s+(?:#(\d+)|https://[^/\s]+/([^/\s]+/[^/\s]+)/issues/(\d+))\b`)

// Due is the component's output: the work issues landed since the last retro,
// the count that makes a retro due and whether it is, where the window starts
// (the last retro's close, or the oldest open retro's creation, or none: the
// whole history), and how much the names held.
type Due struct {
	Landed   int    `json:"landed"`
	DueAfter int    `json:"due_after"`
	Due      bool   `json:"due"`
	Since    string `json:"since"`
	Retro    int    `json:"retro"`
	Issues   int    `json:"issues"`
	Pulls    int    `json:"pulls"`
}

// In is what the derivation reads.
type In struct {
	Issues   map[string]github.Snapshot `index:"issues"`
	Pulls    map[string]github.Snapshot `index:"pulls"`
	DueAfter int                        `index:"config/due-after"`
	Tracker  string                     `index:"config/tracker"`
	Base     string                     `index:"config/base"`
}

// Component is the component a binary carries.
var Component = index.Declare(Name, "Whether a retro is due: the work issues landed since the last one, from the GitHub names.",
	index.Config("due-after", 10, "How many landed work issues make a retro due: se.toml [retro] due_after."),
	index.Config("tracker", "", "The tracker, <owner>/<repo>: a pull request's Fixes or Refs URL names an issue only there."),
	index.Config("base", "main", "The integration branch: a work issue landed where a pull request naming it merged into it."),
	index.Derived("due", Due{DueAfter: 10}, "The work issues landed since the last retro and whether a retro is due.",
		func(in In) (Due, error) { return Count(in), nil }),
)

func init() { index.Register(Component) }

func isRetro(i snap.Issue) bool { return strings.HasPrefix(i.Title, TitleStem) || i.Has(Label) }

// Count is retro.py landed_since_retro over what the names hold.
func Count(in In) Due {
	all := snap.Issues(in.Issues)
	pulls := snap.Pulls(in.Pulls)
	d := Due{DueAfter: in.DueAfter, Issues: len(all), Pulls: len(pulls)}
	var last *snap.Issue
	var lastAt time.Time
	for i := range all {
		c, ok := snap.When(all[i].ClosedAt)
		if all[i].State == "closed" && isRetro(all[i]) && ok && (last == nil || c.After(lastAt)) {
			last, lastAt = &all[i], c
		}
	}
	var since time.Time
	hasSince := false
	switch {
	case last != nil:
		since, hasSince, d.Since, d.Retro = lastAt, true, last.ClosedAt, last.Number
	default:
		var oldest *snap.Issue
		var oldestAt time.Time
		for i := range all {
			c, ok := snap.When(all[i].CreatedAt)
			if all[i].State == "open" && isRetro(all[i]) && ok && (oldest == nil || c.Before(oldestAt)) {
				oldest, oldestAt = &all[i], c
			}
		}
		if oldest != nil {
			since, hasSince, d.Since, d.Retro = oldestAt, true, oldest.CreatedAt, oldest.Number
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
		duplicate := i.Reason == "duplicate" || i.Has("duplicate")
		if landed && !duplicate && i.Reason != "not_planned" {
			d.Landed++
		}
	}
	d.Due = d.DueAfter > 0 && d.Landed >= d.DueAfter
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
