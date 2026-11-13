// Package snap reads the GitHub snapshot names kern's GitHub component writes
// (kern/components/github), whichever backend read them: GitHub's REST JSON
// through the token, the session's tool JSON through the relay. It is SE's
// one reader of a snapshot's fields, so the fleet and retro-due components read
// an issue and a pull request the same way, and as SE's Python reads them
// (scripts/work_tickets.py fleet_issue and fleet_pull, scripts/retro.py
// issue_of and pull_of).
package snap

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/mb-89/kern/components/github"
)

// Issue is an issue as SE's components read it.
type Issue struct {
	Number    int
	Repo      string
	Title     string
	State     string // lower case
	Reason    string // the state reason, lower case
	Labels    []string
	Body      string
	URL       string
	ClosedAt  string
	CreatedAt string
	UpdatedAt string
}

// Has says whether the issue carries the label, as written.
func (i Issue) Has(label string) bool {
	for _, l := range i.Labels {
		if l == label {
			return true
		}
	}
	return false
}

// Pull is a pull request as SE's components read it.
type Pull struct {
	Number    int
	Repo      string
	State     string // lower case
	Head      string
	HeadSHA   string
	Base      string
	Body      string
	Mergeable string // the mergeable state, lower case
	MergedAt  string
}

// Issues reads every issue snapshot, lowest number first.
func Issues(family map[string]github.Snapshot) []Issue {
	var out []Issue
	for _, s := range family {
		d, ok := s.Data.(map[string]any)
		if !ok {
			continue
		}
		out = append(out, Issue{
			Number: number(d, s), Repo: s.Repo, Title: str(d, "title"),
			State: strings.ToLower(str(d, "state")), Reason: strings.ToLower(str(d, "state_reason", "stateReason")),
			Labels: labels(d["labels"]), Body: str(d, "body"), URL: str(d, "html_url", "url"),
			ClosedAt: str(d, "closed_at", "closedAt"), CreatedAt: str(d, "created_at", "createdAt"),
			UpdatedAt: str(d, "updated_at", "updatedAt"),
		})
	}
	sort.Slice(out, func(a, b int) bool { return out[a].Number < out[b].Number })
	return out
}

// Pulls reads every pull request snapshot, lowest number first.
func Pulls(family map[string]github.Snapshot) []Pull {
	var out []Pull
	for _, s := range family {
		d, ok := s.Data.(map[string]any)
		if !ok {
			continue
		}
		head, _ := d["head"].(map[string]any)
		base, _ := d["base"].(map[string]any)
		out = append(out, Pull{
			Number: number(d, s), Repo: s.Repo, State: strings.ToLower(str(d, "state")),
			Head: or(str(head, "ref"), str(d, "headRefName")), HeadSHA: or(str(head, "sha"), str(d, "headRefOid")),
			Base: or(str(base, "ref"), str(d, "baseRefName")), Body: str(d, "body"),
			Mergeable: strings.ToLower(str(d, "mergeable_state", "mergeStateStatus")),
			MergedAt:  str(d, "merged_at", "mergedAt"),
		})
	}
	sort.Slice(out, func(a, b int) bool { return out[a].Number < out[b].Number })
	return out
}

// Conclusion is the conclusion, lower case, of the first check run named
// name in a check-runs snapshot, "" where it has none: the REST answer's
// check_runs, or the tool's list, bare or under check_runs.
func Conclusion(s github.Snapshot, name string) string {
	runs := s.Data
	if d, ok := runs.(map[string]any); ok {
		runs = d["check_runs"]
	}
	list, _ := runs.([]any)
	for _, r := range list {
		run, ok := r.(map[string]any)
		if ok && str(run, "name") == name {
			return strings.ToLower(str(run, "conclusion"))
		}
	}
	return ""
}

// When reads a time as GitHub writes it; ok is false for none.
func When(s string) (time.Time, bool) {
	if s == "" {
		return time.Time{}, false
	}
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return time.Time{}, false
	}
	return t, true
}

func number(d map[string]any, s github.Snapshot) int {
	if n, ok := d["number"].(float64); ok {
		return int(n)
	}
	return s.Number
}

// str answers the first of keys d holds a non-empty value for, as text.
func str(d map[string]any, keys ...string) string {
	for _, k := range keys {
		switch v := d[k].(type) {
		case nil:
		case string:
			if v != "" {
				return v
			}
		case float64:
			return fmt.Sprint(int64(v))
		default:
			return fmt.Sprint(v)
		}
	}
	return ""
}

// labels reads label names: a list of objects with a name, or of names, or
// GraphQL's {"nodes": [...]}.
func labels(v any) []string {
	if d, ok := v.(map[string]any); ok {
		v = d["nodes"]
	}
	list, _ := v.([]any)
	var out []string
	for _, l := range list {
		switch l := l.(type) {
		case map[string]any:
			out = append(out, str(l, "name"))
		case string:
			out = append(out, l)
		}
	}
	return out
}

func or(a, b string) string {
	if a != "" {
		return a
	}
	return b
}
