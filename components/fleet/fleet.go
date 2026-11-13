// Package fleet is SE's fleet component: the fleet check's rules
// (scripts/work_tickets.py fleet_findings) as a derivation over kern's
// GitHub snapshot names and origin's branches, so the greeting and the
// integrator read what is stuck or stray live. It is SE's, not kern's: the
// rules are SE's work model. The Python fleet-check stays the path where no
// core carries this component, and the agreement test holds both to one
// answer on one snapshot (fleet_test.go).
package fleet

import (
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/kern/index"
	"github.com/mb-89/se/components/snap"
)

// Name is the component's name, which the wiring's instances name.
const Name = "fleet"

// The kinds, in the order the findings are listed: work_tickets.py FLEET_KINDS.
var Kinds = []string{"no branch", "quiet branch", "failed check", "conflict", "stray branch",
	"impossible block", "block cycle", "waiting on the person"}

// SE's marks, as work_tickets.py names them.
const (
	InProgress  = "in-progress"
	Person      = "se-person"
	CheckName   = "check"
	ReportBegin = "<!-- se:field-report -->"
	routing     = "Routing"
)

var failed = map[string]bool{"failure": true, "timed_out": true, "cancelled": true,
	"startup_failure": true, "action_required": true}

var workIssue = regexp.MustCompile(`(?i)\bWork issue:\*{0,2}\s*#(\d+)\b`)

// Finding is one stuck or stray piece of work, with its remedy: the shape of
// fleet-check --json's findings.
type Finding struct {
	Kind   string  `json:"kind"`
	Issue  int     `json:"issue"`
	Pull   *int    `json:"pull"`
	Branch *string `json:"branch"`
	What   string  `json:"what"`
	Remedy string  `json:"remedy"`
	Holds  []int   `json:"holds"`
}

// Findings is the component's output: the findings, when they were
// computed and how much of the fleet the names held, so a reader can tell a
// core that has read nothing yet from a healthy fleet.
type Findings struct {
	At       time.Time `json:"at"`
	Issues   int       `json:"issues"`
	Pulls    int       `json:"pulls"`
	Branches int       `json:"branches"`
	Healthy  bool      `json:"healthy"`
	Findings []Finding `json:"findings"`
}

// In is what the derivation reads: the GitHub families whole, origin's
// branches and the config.
type In struct {
	Issues     map[string]github.Snapshot `index:"issues"`
	Pulls      map[string]github.Snapshot `index:"pulls"`
	Checks     map[string]github.Snapshot `index:"checks"`
	Branches   map[string]time.Time       `index:"branches"`
	LeaseHours float64                    `index:"config/lease-hours"`
	Repository string                     `index:"config/repository"`
	Base       string                     `index:"config/base"`
}

// Now is the clock the lease is counted on; a test replaces it.
var Now = time.Now

// Component is the component a binary carries.
var Component = index.Declare(Name, "What is stuck or stray in the fleet, with its remedy, from the GitHub names.",
	index.Config("lease-hours", 3.0, "How long in-progress work may go without a push to its branch: se.toml [fleet] lease_hours."),
	index.Config("repository", "", "The checkout's repository name: an issue labelled repo:<other> keeps its branch elsewhere."),
	index.Config("base", "main", "The integration branch: the pull requests to it are the delivered work."),
	index.Derived("findings", Findings{Healthy: true, Findings: []Finding{}}, "Each stuck or stray piece of work, with its remedy, as fleet-check --json lists it.",
		func(in In) (Findings, error) { return Check(in, Now().UTC()), nil }),
)

func init() { index.Register(Component) }

type issue = snap.Issue

// Check is the fleet check over in at now: work_tickets.py fleet_findings,
// rule for rule, on what the names hold. The names carry no comments, so the
// lease of in-progress work without a branch is never counted from a Started
// comment, as the Python check answers where it read none.
func Check(in In, now time.Time) Findings {
	lease := time.Duration(in.LeaseHours * float64(time.Hour))
	leaseText := strconv.FormatFloat(in.LeaseHours, 'g', 6, 64)
	open, closed := map[int]issue{}, map[int]issue{}
	all := snap.Issues(in.Issues)
	for _, i := range all {
		switch i.State {
		case "open":
			open[i.Number] = i
		case "closed":
			closed[i.Number] = i
		}
	}
	checks := map[int]github.Snapshot{}
	for _, s := range in.Checks {
		checks[s.Number] = s
	}
	var pulls []snap.Pull
	for _, p := range snap.Pulls(in.Pulls) {
		if p.State == "open" && p.Base == in.Base {
			pulls = append(pulls, p)
		}
	}
	var found []Finding
	add := func(f Finding) {
		if f.Holds == nil {
			f.Holds = []int{}
		}
		found = append(found, f)
	}
	here := func(i issue) bool {
		var repos []string
		for _, l := range i.Labels {
			if strings.HasPrefix(strings.ToLower(l), "repo:") {
				repos = append(repos, strings.ToLower(l))
			}
		}
		if len(repos) == 0 {
			return true
		}
		for _, r := range repos {
			if r == "repo:"+strings.ToLower(in.Repository) {
				return true
			}
		}
		return false
	}

	for _, n := range sortedKeys(open) {
		i := open[n]
		if !i.Has(InProgress) || !here(i) {
			continue
		}
		branch := i.Title
		pushed, ok := in.Branches[branch]
		if !ok {
			add(Finding{Kind: "no branch", Issue: n, Branch: &branch,
				What:   fmt.Sprintf("in progress, but origin has no branch %s, and the lease cannot be counted: its comments were not read", branch),
				Remedy: fmt.Sprintf("start a worker on #%d (work_tickets.py start), or take in-progress off and label it ready", n)})
		} else if now.Sub(pushed) > lease {
			hours := int(math.Floor(now.Sub(pushed).Hours()))
			add(Finding{Kind: "quiet branch", Issue: n, Branch: &branch,
				What:   fmt.Sprintf("no push to %s for %d hours, over the lease of %s", branch, hours, leaseText),
				Remedy: fmt.Sprintf("read its worker's session; where it stopped, start a worker again on %s, which syncs and delivers what it has", branch)})
		}
	}
	for _, p := range pulls {
		if !strings.Contains(p.Body, ReportBegin) {
			continue
		}
		number := 0
		if m := workIssue.FindStringSubmatch(p.Body); m != nil {
			number, _ = strconv.Atoi(m[1])
		} else {
			for _, n := range sortedKeys(open) {
				if open[n].Title == p.Head {
					number = n
					break
				}
			}
		}
		pull, head := p.Number, p.Head
		check := ""
		if s, ok := checks[p.Number]; ok {
			check = snap.Conclusion(s, CheckName)
		}
		if failed[check] {
			add(Finding{Kind: "failed check", Issue: number, Pull: &pull, Branch: &head,
				What:   fmt.Sprintf("%s concluded %s on %s", CheckName, check, head),
				Remedy: fmt.Sprintf("a worker on %s syncs, makes %s pass and delivers again", head, CheckName)})
		}
		if p.Mergeable == "dirty" || p.Mergeable == "conflicting" {
			add(Finding{Kind: "conflict", Issue: number, Pull: &pull, Branch: &head,
				What:   fmt.Sprintf("%s conflicts with the integration branch", head),
				Remedy: fmt.Sprintf("a worker on %s runs work_tickets.py sync (merge origin/main, never rebase), resolves and delivers again", head)})
		}
	}

	inUse := map[string]bool{}
	for _, i := range open {
		inUse[i.Title] = true
	}
	for _, p := range pulls {
		inUse[p.Head] = true
	}
	for _, n := range sortedKeys(closed) {
		i := closed[n]
		branch := i.Title
		if _, ok := in.Branches[branch]; ok && !inUse[branch] && here(i) {
			add(Finding{Kind: "stray branch", Issue: n, Branch: &branch,
				What:   fmt.Sprintf("#%d is closed, but origin still has %s", n, branch),
				Remedy: fmt.Sprintf("git push origin --delete %s, once nothing on it is wanted", branch)})
		}
	}

	blocked := map[int][]int{}
	for n, i := range open {
		blocked[n] = Blockers(i.Body)
	}
	for _, n := range sortedKeys(blocked) {
		for _, b := range blocked[n] {
			if _, ok := open[b]; ok {
				continue
			}
			if i, ok := closed[b]; ok && i.Reason == "not_planned" {
				add(Finding{Kind: "impossible block", Issue: n,
					What:   fmt.Sprintf("blocked by #%d, closed as not planned", b),
					Remedy: fmt.Sprintf("take #%d out of #%d's Blocked by and its dependency, or close #%d too", b, n, n)})
			}
		}
	}
	cycles := map[int]bool{}
	for _, start := range sortedKeys(blocked) {
		path, seen := []int{start}, map[int]bool{start: true}
		for len(path) > 0 {
			var following []int
			for _, b := range blocked[path[len(path)-1]] {
				if _, ok := blocked[b]; ok {
					following = append(following, b)
				}
			}
			if contains(following, start) {
				if !cycles[start] {
					for _, n := range path {
						cycles[n] = true
					}
					loop := make([]string, 0, len(path)+1)
					for _, n := range append(append([]int{}, path...), start) {
						loop = append(loop, fmt.Sprintf("#%d", n))
					}
					add(Finding{Kind: "block cycle", Issue: start,
						What:   "blocked by itself: " + strings.Join(loop, " -> "),
						Remedy: "SE decides which of them does not block the other and takes that block out"})
				}
				break
			}
			step, ok := 0, false
			for _, b := range following {
				if !seen[b] {
					step, ok = b, true
					break
				}
			}
			if !ok {
				break
			}
			path = append(path, step)
			seen[step] = true
		}
	}

	for _, n := range sortedKeys(open) {
		if !open[n].Has(Person) {
			continue
		}
		holds, queue := map[int]bool{}, []int{n}
		for len(queue) > 0 {
			current := queue[len(queue)-1]
			queue = queue[:len(queue)-1]
			for waiting, blockers := range blocked {
				if contains(blockers, current) && !holds[waiting] && waiting != n {
					holds[waiting] = true
					queue = append(queue, waiting)
				}
			}
		}
		held := sortedKeys(holds)
		what := fmt.Sprintf("waits for the person (%s)", Person)
		if len(held) > 0 {
			names := make([]string, len(held))
			for i, h := range held {
				names[i] = fmt.Sprintf("#%d", h)
			}
			what += ", holding up " + strings.Join(names, ", ")
		}
		add(Finding{Kind: "waiting on the person", Issue: n, What: what,
			Remedy: "SE presents it to the person with the decision skill", Holds: held})
	}

	rank := map[string]int{}
	for i, k := range Kinds {
		rank[k] = i
	}
	sort.SliceStable(found, func(a, b int) bool {
		if rank[found[a].Kind] != rank[found[b].Kind] {
			return rank[found[a].Kind] < rank[found[b].Kind]
		}
		return found[a].Issue < found[b].Issue
	})
	if found == nil {
		found = []Finding{}
	}
	return Findings{At: now, Issues: len(all), Pulls: len(in.Pulls), Branches: len(in.Branches),
		Healthy: len(found) == 0, Findings: found}
}

// Blockers are the issues of the same repository a body's Blocked by names:
// work_tickets.py blockers_of, its own "## Blocked by" and the routed one.
func Blockers(body string) []int {
	sections := markdownSections(body, 2)
	text := section(sections, "blocked by")
	routed := section(markdownSections(section(sections, strings.ToLower(routing)), 3), "blocked by")
	if routed != "" {
		if text != "" {
			text += "\n\n" + routed
		} else {
			text = routed
		}
	}
	set := map[int]bool{}
	r := []rune(text)
	for i := 0; i < len(r); i++ {
		if r[i] != '#' || (i > 0 && (word(r[i-1]) || strings.ContainsRune("/.-", r[i-1]))) {
			continue
		}
		j := i + 1
		for j < len(r) && r[j] >= '0' && r[j] <= '9' {
			j++
		}
		if j == i+1 || (j < len(r) && word(r[j])) {
			continue
		}
		n, _ := strconv.Atoi(string(r[i+1 : j]))
		set[n] = true
	}
	return sortedKeys(set)
}

func word(r rune) bool { return r == '_' || unicode.IsLetter(r) || unicode.IsDigit(r) }

var comment = regexp.MustCompile(`(?s)<!--.*?-->`)

type sections struct {
	order []string
	text  map[string][]string
}

// markdownSections is work_tickets.py markdown_sections: the sections at one
// heading level, outside fences, heading (case-folded) to text.
func markdownSections(body string, level int) sections {
	heading := regexp.MustCompile(`^` + strings.Repeat("#", level) + `\s+(.+?)\s*$`)
	s := sections{text: map[string][]string{}}
	current := ""
	in, fenced := false, false
	for _, line := range strings.Split(strings.ReplaceAll(body, "\r\n", "\n"), "\n") {
		if strings.HasPrefix(strings.TrimLeft(line, " \t"), "```") {
			fenced = !fenced
		}
		var m []string
		if !fenced {
			m = heading.FindStringSubmatch(line)
		}
		if m != nil {
			current, in = strings.ToLower(strings.TrimSpace(m[1])), true
			if _, ok := s.text[current]; !ok {
				s.order = append(s.order, current)
				s.text[current] = []string{}
			}
		} else if in {
			s.text[current] = append(s.text[current], line)
		}
	}
	return s
}

// section is the text of the first section whose heading starts with name.
func section(s sections, name string) string {
	for _, h := range s.order {
		if strings.HasPrefix(h, name) {
			return strings.TrimSpace(comment.ReplaceAllString(strings.Join(s.text[h], "\n"), ""))
		}
	}
	return ""
}

func contains(list []int, n int) bool {
	for _, x := range list {
		if x == n {
			return true
		}
	}
	return false
}

func sortedKeys[V any](m map[int]V) []int {
	keys := make([]int, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Ints(keys)
	return keys
}
