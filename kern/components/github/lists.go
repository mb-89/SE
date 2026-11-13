package github

import (
	"fmt"
	"net/url"
	"sort"
	"strings"
	"time"

	"github.com/mb-89/kern/index"
)

// listKind is one family of list reads: its output, its verb, the tool that
// lists it in a session and the REST path that lists it with a token.
type listKind struct {
	port, verb, help string
	tool, path       string
	labels           bool // whether a read may name labels
}

var (
	issueLists = listKind{port: "issue-lists", verb: "issue-list", help: "a repository's issues in one state, optionally those carrying every label named", tool: "list_issues", path: "issues", labels: true}
	pullLists  = listKind{port: "pull-lists", verb: "pull-list", help: "a repository's pull requests in one state", tool: "list_pull_requests", path: "pulls"}
	lists      = []listKind{issueLists, pullLists}
)

// The states a list read names; open is the default.
var states = map[string]bool{"open": true, "closed": true, "all": true}

// perPage is the page size the relay's steps and the token's reads ask.
const perPage = 100

// toolPerPage is the page size the GitHub tools answer where a call names
// none: the REST API's default.
const toolPerPage = 30

func (l listKind) out() *index.FamilyPort[List] {
	if l.port == issueLists.port {
		return issueListsOut
	}
	return pullListsOut
}

// ListKey is the key a list read stands at in its family:
// <owner>.<repo>.<state>, then each label in lower case and in order, every
// character outside letters, digits, dashes and underscores written as a dash.
func ListKey(r ListRef) string {
	key := strings.ToLower(r.Owner) + "." + strings.ToLower(r.Repo) + "." + r.State
	for _, l := range labelsOf(r.Labels) {
		key += "." + strings.Map(func(c rune) rune {
			if c == '-' || c == '_' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' {
				return c
			}
			return '-'
		}, strings.ToLower(l))
	}
	return key
}

// labelsOf is a read's labels as its key and its list name them: trimmed, in order.
func labelsOf(labels []string) []string {
	out := []string{}
	for _, l := range labels {
		if l = strings.TrimSpace(l); l != "" {
			out = append(out, l)
		}
	}
	sort.Slice(out, func(i, j int) bool { return strings.ToLower(out[i]) < strings.ToLower(out[j]) })
	return out
}

// listOutboxKey is the key a list read's step stands at in the outbox: <verb>.<key>.
func listOutboxKey(l listKind, r ListRef) string { return l.verb + "." + ListKey(r) }

// norm checks a list read and gives it its default state and its labels in order.
func (l listKind) norm(r ListRef) (ListRef, error) {
	r.State = strings.ToLower(strings.TrimSpace(r.State))
	if r.State == "" {
		r.State = "open"
	}
	r.Labels = labelsOf(r.Labels)
	switch {
	case r.Owner == "" || r.Repo == "":
		return r, fmt.Errorf("github %s: a list names the owner and the repository, not %+v", l.verb, r)
	case !states[r.State]:
		return r, fmt.Errorf("github %s: state %q is none of open, closed and all", l.verb, r.State)
	case len(r.Labels) > 0 && !l.labels:
		return r, fmt.Errorf("github %s: GitHub lists pull requests by no label; list issues by label instead", l.verb)
	}
	if len(r.Labels) == 0 {
		r.Labels = nil
	}
	return r, nil
}

// list answers one list read through the backend chosen at start.
func (g *GitHub) list(l listKind, r ListRef) (List, error) {
	r, err := l.norm(r)
	if err != nil {
		return List{}, err
	}
	g.mu.Lock()
	backend, rest := g.backend, g.rest
	g.mu.Unlock()
	switch backend {
	case Token:
		return g.listToken(rest, l, r)
	case Relay:
		v, err := g.ask(l.verb, ListKey(r), listOutboxKey(l, r), listStepOf(l, r, g.o.Now(), nil))
		list, _ := v.(List)
		return list, err
	}
	return List{}, fmt.Errorf("github %s: the component has not started", l.verb)
}

// listToken lists through REST, every page, writes the list and holds it for the refresh.
func (g *GitHub) listToken(rest *rest, l listKind, r ListRef) (List, error) {
	q := url.Values{"state": {r.State}}
	if len(r.Labels) > 0 {
		q.Set("labels", strings.Join(r.Labels, ","))
	}
	// GitHub's issues list holds pull requests too; the issue list keeps issues alone.
	keep := func(item any) bool {
		m, _ := item.(map[string]any)
		_, pull := m["pull_request"]
		return l.port != issueLists.port || !pull
	}
	items, err := rest.pages(repoPath(r.Owner, r.Repo)+"/"+l.path, q, keep)
	if err != nil {
		return List{}, fmt.Errorf("github %s %s: %w", l.verb, ListKey(r), err)
	}
	list := List{Repo: repoOf(r.Owner, r.Repo), State: r.State, Labels: r.Labels, Read: g.o.Now().UTC(), Via: Token, Data: items}
	ob := listOutboxKey(l, r)
	g.mu.Lock()
	g.held[ob] = func() { _, _ = g.listToken(rest, l, r) }
	g.mu.Unlock()
	return list, g.land(ob, l.out().At(ListKey(r), list), list)
}

// listStepOf is the tool call that lists r in a session, at the page next
// names (nil for the first).
func listStepOf(l listKind, r ListRef, asked time.Time, next map[string]any) Step {
	in := map[string]any{"owner": r.Owner, "repo": r.Repo, "perPage": perPage}
	switch l.port {
	case issueLists.port:
		if r.State != "all" { // list_issues lists both states where it names none
			in["state"] = strings.ToUpper(r.State)
		}
		if len(r.Labels) > 0 {
			in["labels"] = r.Labels
		}
	default:
		in["state"] = r.State
	}
	for k, v := range next {
		in[k] = v
	}
	return Step{Tool: l.tool, Asked: asked.UTC(), Input: in}
}

// matchList answers the list read a tool use is: list_issues or
// list_pull_requests with an owner, a repository and nothing that narrows
// or reshapes the list beyond its state and labels (fields, since, a sort,
// a branch), as those name another list than the one a list name holds.
func matchList(use toolUse, bare string) (listKind, ListRef, bool) {
	for _, l := range lists {
		if l.tool != bare {
			continue
		}
		r := ListRef{}
		for k, v := range use.Input {
			switch k {
			case "owner":
				r.Owner, _ = v.(string)
			case "repo":
				r.Repo, _ = v.(string)
			case "state":
				r.State, _ = v.(string)
			case "labels":
				if !l.labels {
					return listKind{}, ListRef{}, false
				}
				vs, _ := v.([]any)
				for _, x := range vs {
					s, _ := x.(string)
					r.Labels = append(r.Labels, s)
				}
			case "perPage", "page", "after":
			default:
				return listKind{}, ListRef{}, false
			}
		}
		if r.State == "" && l.port == issueLists.port {
			r.State = "all" // list_issues without a state lists both
		}
		r, err := l.norm(r)
		return l, r, err == nil
	}
	return listKind{}, ListRef{}, false
}
