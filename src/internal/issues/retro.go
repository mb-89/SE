package issues

import (
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// NewMark is what se issue new leaves at the end of every body it writes, so
// the retro can tell an issue it made from one made by hand.
const NewMark = "<!-- se:new -->"

// unattendedMark is in the body of a retro no person started, which asked for
// no field feedback. One a person started carries <!-- se:retro attended -->
// instead. Either way its box files the issues and closes it.
const unattendedMark = "<!-- se:retro unattended -->"

// RetroIssue is the retro se retro new created.
type RetroIssue struct {
	Issue
	// Previous is the last closed retro, whose closing opens this one's
	// window; 0 where there is none, and the window is the whole history.
	Previous   int  `json:"previous"`
	Unattended bool `json:"unattended"`
}

// past is a closed issue or pull request, as the retro reads it.
type past struct {
	issue
	ClosedAt time.Time `json:"closed_at"`
}

// lastRetro is the closed retro that closed last, apart from n; ok is false
// where none has closed.
func (s Source) lastRetro(n int) (last past, ok bool, all []past, err error) {
	return s.lastClosed(RetroLabel, n)
}

// lastClosed is the closed issue labelled label that closed last, apart from
// n and those closed as duplicates, which never ran, and all of them, oldest
// first; ok is false where none has closed.
func (s Source) lastClosed(label string, n int) (last past, ok bool, all []past, err error) {
	list, err := api[past](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100", s.Repo, label), true)
	if err != nil {
		return past{}, false, nil, err
	}
	for _, r := range list {
		if r.PullRequest != nil || r.Number == n || !ran(r) {
			continue
		}
		all = append(all, r)
		if !ok || r.ClosedAt.After(last.ClosedAt) {
			last, ok = r, true
		}
	}
	sort.Slice(all, func(a, b int) bool { return all[a].ClosedAt.Before(all[b].ClosedAt) })
	return last, ok, all, nil
}

// NewRetro creates a retro issue, labelled se and se-retro: field is the
// person's field feedback ("" for none), unattended says nobody waits for its
// report. It goes through the same code as se issue new.
func (s Source) NewRetro(field string, unattended bool) (RetroIssue, error) {
	last, ok, _, err := s.lastRetro(0)
	if err != nil {
		return RetroIssue{}, err
	}
	window := "the repository's whole history: no retro has closed yet"
	r := RetroIssue{Unattended: unattended}
	if ok {
		r.Previous = last.Number
		window = fmt.Sprintf("everything closed since the retro #%d closed, %s", last.Number, last.ClosedAt.UTC().Format(time.RFC3339))
	}
	mode, who := "attended", "A person started it. The box creates the findings' issues, those for a person where controversial, and closes it."
	if unattended {
		mode, who = "unattended", "It runs unattended. The box creates the findings' issues, those for a person where controversial, and closes it."
	}
	feedback := strings.TrimSpace(field)
	switch {
	case feedback == "" && unattended:
		feedback = "None: started unattended."
	case feedback == "":
		feedback = "None given."
	}
	body := fmt.Sprintf("A retro over %s. The rules are spec/retro.md; a box takes it and starts its agent, se:retro, which starts with `se retro collect`.\n\n%s\n\n## Field feedback\n%s\n\n<!-- se:retro %s -->",
		window, who, feedback, mode)
	title := "SE retro " + s.now().UTC().Format("2006-01-02")
	made, _, err := s.create(title, body, 0, nil, []string{Label, RetroLabel})
	if err != nil {
		return RetroIssue{}, err
	}
	r.Issue = made
	return r, nil
}

// RetroWindow is what a retro looks at: everything closed after Since, the closing
// of the retro Previous, up to Until. A zero Since is the whole history.
type RetroWindow struct {
	Previous int       `yaml:"previous"`
	Since    time.Time `yaml:"since,omitempty"`
	Until    time.Time `yaml:"until"`
}

func (w RetroWindow) holds(t time.Time) bool {
	return !t.IsZero() && t.After(w.Since) && !t.After(w.Until)
}

// since is the query that narrows a list to what changed in the window.
func (w RetroWindow) since() string {
	if w.Since.IsZero() {
		return ""
	}
	return "&since=" + w.Since.UTC().Format(time.RFC3339)
}

// Broken is one rule a retro found broken in its window.
type Broken struct {
	// Kind is the rule: fixes, ci, outside-pr, mark or answers (see checkKinds).
	Kind    string `yaml:"kind" json:"kind"`
	Subject string `yaml:"subject" json:"subject"`
	What    string `yaml:"what" json:"what"`
}

// RuleCheck is one rule a retro holds its window to.
type RuleCheck struct {
	Kind string
	Rule string
	// Since is the merged PR that brought the rule, 0 where it held from the
	// first commit. A retro checks the rule only on what came after it, by Bound.
	Since int
	// Bound is the time Since is held against: when what the rule checks
	// closed, or, for a rule on what is written at creation, when it was made.
	Bound Bound
}

// Bound says which time of an issue or PR a rule check's start is held against.
type Bound string

const (
	// Closing bounds a check by when what it checks closed (a PR's merge).
	Closing Bound = "closed"
	// Creation bounds a check by when what it checks was created.
	Creation Bound = "created"
)

// at is the time of x the check's start is held against.
func (k RuleCheck) at(closed, created time.Time) time.Time {
	if k.Bound == Creation {
		return created
	}
	return closed
}

// checkKinds are the rule checks, in the order the report lists them. spec/retro.md
// lists them from here.
var checkKinds = []RuleCheck{
	{"fixes", "every merged PR said `Fixes #n`", 14, Closing},
	{"ci", "every merged PR had green CI (the last run of each check on its head)", 0, Closing},
	{"outside-pr", "no commit reached main outside a PR (every commit on main is some merged PR's merge commit)", 0, Closing},
	// The mark is written at creation, so an issue made before #91 is not held to it.
	{"mark", "every `se` issue carries `se issue new`'s mark, `<!-- se:new -->`, which it writes at the end of every body", 91, Creation},
	{"answers", "every landed issue (a leaf closed as completed, not a retro, an overhaul or a person's decision) has landing answers", 74, Closing},
}

// RuleChecks are the rule checks, in the order the report lists them.
func RuleChecks() []RuleCheck { return append([]RuleCheck(nil), checkKinds...) }

// Row is one closed issue of the window: a row of the matrix, with its counts.
type Row struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	// Reason is GitHub's state_reason: completed, not_planned, duplicate.
	Reason string `json:"reason"`
	// Answers are its landing answers, by key; nil where it has none.
	Answers map[string]string `json:"answers,omitempty"`
	// Landed says it is a landed issue, one the answers check holds to its
	// landing answers: a leaf closed as completed, not a retro, an overhaul
	// or a person's decision. The per-issue metrics divide by these.
	Landed bool `json:"landed"`
	// ForPerson says it is an issue for a person (se-person).
	ForPerson bool `json:"for_person"`
	// PR is the merged PR that fixed it, 0 for none.
	PR        int `json:"pr,omitempty"`
	Takeovers int `json:"takeovers"`
	Conflicts int `json:"conflicts"`
	Person    int `json:"person"`
	// Minutes is the time from its claim to its PR's merge, or, for a leaf
	// landed into its manifest, to that landing; -1 unknown.
	Minutes int `json:"minutes"`
	// Requests is the GitHub requests its landing facts counted; 0 unknown.
	Requests int `json:"requests,omitempty"`
	// Into is the manifest's branch a leaf landed into, from its landing
	// facts; empty for an issue that landed as a PR.
	Into string `json:"into,omitempty"`
}

// Script is a file added under src/scripts/ in the window.
type Script struct {
	Path  string `yaml:"path" json:"path"`
	PR    int    `yaml:"pr" json:"pr"`
	Why   string `yaml:"why" json:"why"`
	Group string `yaml:"group" json:"group"`
}

// merged is the part of a closed pull request the retro reads.
type merged struct {
	Number   int        `json:"number"`
	Title    string     `json:"title"`
	Body     string     `json:"body"`
	MergedAt *time.Time `json:"merged_at"`
	SHA      string     `json:"merge_commit_sha"`
	Head     struct {
		SHA string `json:"sha"`
	} `json:"head"`
}

// Collected is what se retro collect reads from GitHub for retro N.
type Collected struct {
	Retro    int
	Attended bool
	Window   RetroWindow
	Rows     []Row
	PRs      int
	Commits  int
	Reruns   int
	// Reholds counts the issues for a person made in the window beyond the
	// first for each issue they hold back: one hold minted again.
	Reholds int
	Checks  []Broken
	// Before counts, by kind, what broke a rule in the window but closed (or,
	// for a rule bounded by creation, was created) before the PR that brought
	// it merged; Checks leaves it out.
	Before  map[string]int
	Scripts []Script
	Metrics Metrics
	// Previous is the last closed retro's report, Score how it fared; History
	// is every closed retro's metrics, oldest first.
	Previous *RetroReport
	Score    *Score
	History  []Past
}

// Past is an earlier retro's metrics.
type Past struct {
	Retro   int
	Metrics Metrics
}

var (
	fixesLine    = regexp.MustCompile(`(?i)\bfixes #(\d+)\b`)
	takeoverMark = regexp.MustCompile(`<!-- se:takeover (\d+) -->`)
	conflictMark = regexp.MustCompile(`<!-- se:takeover-head [0-9a-f]+ -->`)
	personMark   = regexp.MustCompile(`<!-- se:person -->`)
)

// retroIssue reads retro n: it must be an open issue labelled se-retro.
func (s Source) retroIssue(n int) (issue, error) {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		return issue{}, err
	}
	i := got[0]
	if i.PullRequest != nil || i.State != "open" || !i.labelled(RetroLabel) {
		return issue{}, fmt.Errorf("#%d is not an open retro (an issue labelled %s)", n, RetroLabel)
	}
	return i, nil
}

// Collect reads retro n's window from GitHub: the closed se issues with their
// landing answers and marks, the merged PRs with their CI and scripts, the
// commits on main, and the earlier retros' reports. qs are the landing
// questions.
func (s Source) Collect(n int) (Collected, error) {
	i, err := s.retroIssue(n)
	if err != nil {
		return Collected{}, err
	}
	c := Collected{Retro: n, Attended: !strings.Contains(i.Body, unattendedMark), Window: RetroWindow{Until: s.now().UTC().Truncate(time.Second)}}
	last, ok, retros, err := s.lastRetro(n)
	if err != nil {
		return Collected{}, err
	}
	if ok {
		c.Window.Previous, c.Window.Since = last.Number, last.ClosedAt.UTC()
	}
	for _, r := range retros {
		rep, err := s.postedReport(r.Number)
		if err != nil {
			return Collected{}, err
		}
		if rep == nil {
			continue
		}
		c.History = append(c.History, Past{r.Number, rep.Metrics})
		if r.Number == c.Window.Previous {
			c.Previous = rep
		}
	}

	closed, err := s.closedIn(c.Window, n)
	if err != nil {
		return Collected{}, err
	}
	pulls, inWindow, fixedBy, err := s.merges(c.Window)
	if err != nil {
		return Collected{}, err
	}
	viaPR := map[string]bool{}
	for _, p := range pulls {
		if p.MergedAt != nil {
			viaPR[p.SHA] = true
		}
	}
	c.PRs = len(inWindow)
	started, err := ruleStarts(pulls)
	if err != nil {
		return Collected{}, err
	}
	broke := func(b Broken, at time.Time) {
		if start := started[b.Kind]; !start.IsZero() && !at.After(start) {
			if c.Before == nil {
				c.Before = map[string]int{}
			}
			c.Before[b.Kind]++
			return
		}
		c.Checks = append(c.Checks, b)
	}

	for _, p := range inWindow {
		if fixesLine.FindString(p.Body) == "" {
			broke(Broken{"fixes", fmt.Sprintf("PR #%d", p.Number), fmt.Sprintf("%s: its body names no `Fixes #n`", p.Title)}, *p.MergedAt)
		}
		red, reruns, err := s.mergedCI(p.Head.SHA)
		if err != nil {
			return Collected{}, err
		}
		c.Reruns += reruns
		if red != "" {
			broke(Broken{"ci", fmt.Sprintf("PR #%d", p.Number), fmt.Sprintf("%s: %s", p.Title, red)}, *p.MergedAt)
		}
		scripts, err := s.scriptsOf(p.Number)
		if err != nil {
			return Collected{}, err
		}
		c.Scripts = append(c.Scripts, scripts...)
	}

	commits, err := api[struct {
		SHA    string `json:"sha"`
		Commit struct {
			Message string `json:"message"`
		} `json:"commit"`
	}](s, fmt.Sprintf("repos/%s/commits?sha=main&per_page=100%s&until=%s", s.Repo, c.Window.since(), c.Window.Until.Format(time.RFC3339)), true)
	if err != nil {
		return Collected{}, err
	}
	c.Commits = len(commits)
	for k := len(commits) - 1; k >= 0; k-- {
		m := commits[k]
		if !viaPR[m.SHA] {
			subject, _, _ := strings.Cut(m.Commit.Message, "\n")
			c.Checks = append(c.Checks, Broken{"outside-pr", "commit " + short(m.SHA), subject + ": no merged PR made it"})
		}
	}

	for _, x := range closed {
		row, checks, err := s.row(x, fixedBy)
		if err != nil {
			return Collected{}, err
		}
		c.Rows = append(c.Rows, row)
		for _, b := range checks {
			broke(b, checkKinds[kindOrder(b.Kind)].at(x.ClosedAt, x.Created))
		}
	}
	sort.SliceStable(c.Checks, func(a, b int) bool { return kindOrder(c.Checks[a].Kind) < kindOrder(c.Checks[b].Kind) })
	if c.Reholds, err = s.reholds(c.Window); err != nil {
		return Collected{}, err
	}
	c.Metrics = c.measure()
	if c.Previous != nil {
		score, err := s.score(*c.Previous, c.Checks, c.Metrics)
		if err != nil {
			return Collected{}, err
		}
		c.Score = &score
	}
	return c, nil
}

// merges reads the PRs into main: every one, merged or not, those merged in
// w, lowest number first, and the PR of w that fixed each issue, by its
// Fixes line. The retro and the queue's pace both read them here.
func (s Source) merges(w RetroWindow) (pulls, in []merged, fixedBy map[int]merged, err error) {
	pulls, err = api[merged](s, fmt.Sprintf("repos/%s/pulls?state=closed&base=main&per_page=100", s.Repo), true)
	if err != nil {
		return nil, nil, nil, err
	}
	fixedBy = map[int]merged{}
	for _, p := range pulls {
		if p.MergedAt == nil || !w.holds(*p.MergedAt) {
			continue
		}
		in = append(in, p)
		for _, m := range fixesLine.FindAllStringSubmatch(p.Body, -1) {
			fixedBy[atoi(m[1])] = p
		}
	}
	sort.Slice(in, func(a, b int) bool { return in[a].Number < in[b].Number })
	return pulls, in, fixedBy, nil
}

// closedIn reads the se issues closed in w, lowest number first, skip left
// out. The retro and the queue's pace both read them here.
func (s Source) closedIn(w RetroWindow, skip int) ([]past, error) {
	list, err := api[past](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100%s", s.Repo, Label, w.since()), true)
	if err != nil {
		return nil, err
	}
	var out []past
	for _, x := range list {
		if x.PullRequest == nil && x.Number != skip && w.holds(x.ClosedAt) {
			out = append(out, x)
		}
	}
	sort.Slice(out, func(a, b int) bool { return out[a].Number < out[b].Number })
	return out, nil
}

// reholds counts the issues for a person created in w beyond the first for
// each issue they hold back, open or closed: a hold minted more than once.
func (s Source) reholds(w RetroWindow) (int, error) {
	list, err := api[past](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=all&per_page=100%s", s.Repo, PersonLabel, w.since()), true)
	if err != nil {
		return 0, err
	}
	seen, extra := map[string]bool{}, 0
	for _, x := range list {
		m := holdOf.FindStringSubmatch(x.Title)
		if x.PullRequest != nil || m == nil || !w.holds(x.Created) {
			continue
		}
		if seen[m[1]] {
			extra++
		}
		seen[m[1]] = true
	}
	return extra, nil
}

// ruleStarts are the times the rule checks started: when the PR that brought
// each merged. A rule from the first commit has none.
func ruleStarts(pulls []merged) (map[string]time.Time, error) {
	at := map[int]time.Time{}
	for _, p := range pulls {
		if p.MergedAt != nil {
			at[p.Number] = *p.MergedAt
		}
	}
	starts := map[string]time.Time{}
	for _, k := range checkKinds {
		if k.Since == 0 {
			continue
		}
		t, ok := at[k.Since]
		if !ok {
			return nil, fmt.Errorf("the rule check %s started with PR #%d, which is not a merged PR", k.Kind, k.Since)
		}
		starts[k.Kind] = t
	}
	return starts, nil
}

func kindOrder(kind string) int {
	for k, c := range checkKinds {
		if c.Kind == kind {
			return k
		}
	}
	return len(checkKinds)
}

func short(sha string) string {
	if len(sha) > 7 {
		return sha[:7]
	}
	return sha
}

// row reads one closed issue: its landing answers, its marks, the PR that
// fixed it, and the rules it broke.
func (s Source) row(x past, fixedBy map[int]merged) (Row, []Broken, error) {
	r := Row{Number: x.Number, Title: x.Title, Reason: x.StateReason, Minutes: -1, ForPerson: x.labelled(PersonLabel)}
	subject := "#" + strconv.Itoa(x.Number)
	var checks []Broken
	if !strings.Contains(x.Body, NewMark) {
		checks = append(checks, Broken{"mark", subject, x.Title + ": not made by `se issue new`"})
	}
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, x.Number), true)
	if err != nil {
		return Row{}, nil, err
	}
	rounds := map[string]bool{}
	var landed *Landed
	for _, c := range comments {
		for _, m := range takeoverMark.FindAllStringSubmatch(c.Body, -1) {
			rounds[m[1]] = true
		}
		r.Conflicts += len(conflictMark.FindAllString(c.Body, -1))
		r.Person += len(personMark.FindAllString(c.Body, -1))
		l, ok, err := ParseLanding(c.Body)
		if ok && err != nil {
			checks = append(checks, Broken{"answers", subject, x.Title + ": " + err.Error()})
		}
		if ok && err == nil {
			landed = &l
		}
	}
	r.Takeovers = len(rounds)
	if landed != nil {
		r.Requests = landed.Facts.Requests
	}
	if p, ok := fixedBy[x.Number]; ok {
		r.PR = p.Number
		if landed != nil && !landed.Facts.Claimed.IsZero() {
			r.Minutes = int(p.MergedAt.Sub(landed.Facts.Claimed).Round(time.Minute) / time.Minute)
		}
	} else if landed != nil && landed.Facts.Into != "" {
		// A leaf lands into its manifest's branch, with no PR of its own:
		// its landing's facts carry its time from claim to land.
		r.Into = landed.Facts.Into
		if !landed.Facts.Claimed.IsZero() {
			r.Minutes = landed.Facts.Minutes
		}
	}
	parent := x.SubIssues != nil && x.SubIssues.Total > 0
	// A retro, an overhaul or a person's decision lands no branch, so it has
	// no landing answers by design.
	r.Landed = x.StateReason == "completed" && !parent && !x.labelled(RetroLabel) && !x.labelled(OverhaulLabel) && !r.ForPerson
	if landed != nil {
		r.Answers = landed.Answers
	} else if r.Landed {
		checks = append(checks, Broken{"answers", subject, x.Title + ": closed as completed without landing answers"})
	}
	return r, checks, nil
}

// mergedCI reads the check runs on a merged PR's head: red names what was not
// green at the merge, "" where all was; reruns counts the runs beyond one per
// check.
func (s Source) mergedCI(sha string) (red string, reruns int, err error) {
	got, err := api[struct {
		Runs []struct {
			ID         int64  `json:"id"`
			Name       string `json:"name"`
			Status     string `json:"status"`
			Conclusion string `json:"conclusion"`
		} `json:"check_runs"`
	}](s, fmt.Sprintf("repos/%s/commits/%s/check-runs?filter=all&per_page=100", s.Repo, sha), false)
	if err != nil {
		return "", 0, err
	}
	runs := got[0].Runs
	if len(runs) == 0 {
		return "no check ran on its head", 0, nil
	}
	latest := map[string]int{}
	for k, r := range runs {
		if j, ok := latest[r.Name]; !ok || r.ID > runs[j].ID {
			latest[r.Name] = k
		}
	}
	var bad []string
	for name, k := range latest {
		if r := runs[k]; r.Status != "completed" || failed[r.Conclusion] {
			state := r.Conclusion
			if r.Status != "completed" {
				state = r.Status
			}
			bad = append(bad, fmt.Sprintf("%s %s", name, state))
		}
	}
	sort.Strings(bad)
	if len(bad) > 0 {
		red = "not green at the merge: " + strings.Join(bad, ", ")
	}
	return red, len(runs) - len(latest), nil
}

// scriptsOf lists the files PR n added under src/scripts/, each with the
// comment line at its top that says why it was needed.
func (s Source) scriptsOf(n int) ([]Script, error) {
	files, err := api[struct {
		Name   string `json:"filename"`
		Status string `json:"status"`
		Patch  string `json:"patch"`
	}](s, fmt.Sprintf("repos/%s/pulls/%d/files?per_page=100", s.Repo, n), true)
	if err != nil {
		return nil, err
	}
	var out []Script
	for _, f := range files {
		if f.Status != "added" || !strings.HasPrefix(f.Name, "src/scripts/") || strings.HasSuffix(f.Name, "README.md") {
			continue
		}
		out = append(out, Script{Path: f.Name, PR: n, Why: why(f.Patch), Group: group(f.Name)})
	}
	return out, nil
}

// why is the first comment line of an added file's patch, its shebang aside.
func why(patch string) string {
	for _, line := range strings.Split(patch, "\n") {
		line = strings.TrimSpace(strings.TrimPrefix(line, "+"))
		if strings.HasPrefix(line, "#!") || line == "" || strings.HasPrefix(line, "@@") || line == "package main" {
			continue
		}
		for _, p := range []string{"//", "#", "--"} {
			if rest, ok := strings.CutPrefix(line, p); ok {
				return strings.TrimSpace(rest)
			}
		}
		return ""
	}
	return ""
}

// group is what a script does, read from its name: the word it starts with,
// check-claims.sh is a check.
func group(path string) string {
	base := path[strings.LastIndex(path, "/")+1:]
	word := strings.FieldsFunc(base, func(r rune) bool { return r == '-' || r == '_' || r == '.' })
	if len(word) == 0 {
		return "other"
	}
	return strings.ToLower(word[0])
}

// Metrics are a retro's numbers, by name; the per-issue ones divide by the
// landed issues (those the answers check counts), so retros of different
// sizes compare, and a sweep closing issues for a person or duplicates does
// not dilute them.
type Metrics map[string]float64

// metricNames are the metrics, in the order the report lists them. closed,
// landed and for_person are the window's sizes: every closed issue, the
// landed ones, and the closed issues for a person. duplicates are the closed
// issues closed as duplicate, and the issues for a person made beyond the
// first for each issue they hold back.
var metricNames = []string{
	"closed", "landed", "for_person", "conflicts", "takeovers", "ci_reruns", "person_flags", "by_hand", "duplicates", "requests",
	"conflicts_per_issue", "takeovers_per_issue", "ci_reruns_per_issue", "person_flags_per_issue", "by_hand_per_issue", "duplicates_per_issue", "requests_per_issue",
	"claim_to_merge_minutes",
}

// size says a metric is a size of the window, which moves neither way for
// the better.
func size(name string) bool { return name == "closed" || name == "landed" || name == "for_person" }

func (c Collected) measure() Metrics {
	m := Metrics{"closed": float64(len(c.Rows)), "landed": 0, "for_person": 0, "ci_reruns": float64(c.Reruns), "duplicates": float64(c.Reholds)}
	var minutes []int
	for _, r := range c.Rows {
		if r.Landed {
			m["landed"]++
		}
		if r.ForPerson {
			m["for_person"]++
		}
		m["conflicts"] += float64(r.Conflicts)
		m["takeovers"] += float64(r.Takeovers)
		m["person_flags"] += float64(r.Person)
		m["requests"] += float64(r.Requests)
		if r.Reason == "duplicate" {
			m["duplicates"]++
		}
		if r.Answers != nil && byHand(r.Answers["by-hand"]) {
			m["by_hand"]++
		}
		if r.Minutes >= 0 {
			minutes = append(minutes, r.Minutes)
		}
	}
	for _, name := range counted {
		m[name+"_per_issue"] = 0
		if m["landed"] > 0 {
			m[name+"_per_issue"] = round2(m[name] / m["landed"])
		}
	}
	m["claim_to_merge_minutes"] = float64(median(minutes))
	return m
}

// counted are the metrics counted in the window, each also per landed issue.
var counted = []string{"conflicts", "takeovers", "person_flags", "ci_reruns", "by_hand", "duplicates", "requests"}

// round2 rounds x to two decimals, half away from zero, so a change in a
// metric reads like the metric itself: -0.04, not -0.040000000000000036.
func round2(x float64) float64 { return math.Round(x*100) / 100 }

func median(xs []int) int { return percentile(xs, 0.5) }

// percentile is the value q of the way up xs, sorted (0.5 the median, 0.9
// the p90); 0 for none.
func percentile(xs []int, q float64) int {
	if len(xs) == 0 {
		return 0
	}
	sort.Ints(xs)
	return xs[min(int(q*float64(len(xs))), len(xs)-1)]
}

// commandNamed is an answer naming a command: an se command or a script.
var commandNamed = regexp.MustCompile("(^|[\\s`\"'(])se [a-z]|src/scripts/")

// proposal is an answer saying what a command should, could or would do.
var proposal = regexp.MustCompile(`\b(should|could|would|ought|belongs?)\b`)

// byHand says whether a by-hand answer names a step done by hand, or a
// command that should do it: one that opens with "nothing" counts still
// where it goes on to propose a command, as "Nothing scripted. ... se fleet
// check could run check.sh" does.
func byHand(answer string) bool {
	if !nothing(answer) {
		return true
	}
	a := strings.ToLower(answer)
	return commandNamed.MatchString(a) && proposal.MatchString(a)
}

// nothing says whether an answer says there was nothing: "none", "nothing", "n/a".
func nothing(answer string) bool {
	a := strings.ToLower(strings.TrimSpace(answer))
	for _, w := range []string{"none", "nothing", "n/a", "no", "-"} {
		if a == w || strings.HasPrefix(a, w+".") || strings.HasPrefix(a, w+":") || strings.HasPrefix(a, w+",") || strings.HasPrefix(a, w+" ") && w != "no" {
			return true
		}
	}
	return a == ""
}

// Score is how the previous retro's findings fared.
type Score struct {
	Retro    int         `yaml:"retro"`
	Findings int         `yaml:"findings"`
	Issues   int         `yaml:"issues"`
	Closed   int         `yaml:"closed"`
	Recurred int         `yaml:"recurred"`
	Items    []ScoreItem `yaml:"items"`
}

// ScoreItem is one finding of the previous retro, scored.
type ScoreItem struct {
	Title string `yaml:"title"`
	Class string `yaml:"class"`
	Issue int    `yaml:"issue,omitempty"`
	// State is its issue's: open, completed, not_planned, or none.
	State string `yaml:"state"`
	// Recurred is set where the rule check it named broke again.
	Recurred bool    `yaml:"recurred"`
	Metric   string  `yaml:"metric,omitempty"`
	Before   float64 `yaml:"before,omitempty"`
	Now      float64 `yaml:"now,omitempty"`
	// Dropped says whether its metric moved the right way; nil without one,
	// or where its issue has not closed as completed: a drop is credited to
	// a fix only once it landed.
	Dropped *bool `yaml:"dropped,omitempty"`
}

// score reads how each finding of the previous report fared: did its issue
// close, did the rule check it named break again, did its metric drop. A
// metric's move is judged only where the finding's issue closed as
// completed; before that, no fix of its is on main to credit or blame.
func (s Source) score(prev RetroReport, checks []Broken, now Metrics) (Score, error) {
	broke := map[string]bool{}
	for _, c := range checks {
		broke[c.Kind] = true
	}
	sc := Score{Retro: prev.Retro, Findings: len(prev.Findings)}
	for _, f := range prev.Findings {
		it := ScoreItem{Title: f.Title, Class: f.Class, Issue: f.Issue, State: "none", Recurred: f.Check != "" && broke[f.Check]}
		if f.Issue > 0 {
			sc.Issues++
			got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, f.Issue), false)
			if err != nil {
				return Score{}, err
			}
			it.State = got[0].State
			if got[0].State == "closed" {
				it.State = got[0].StateReason
				if it.State == "completed" {
					sc.Closed++
				}
			}
		}
		if f.Metric != "" {
			before, had := prev.Metrics[f.Metric]
			after, has := now[f.Metric]
			if had && has {
				it.Metric, it.Before, it.Now = f.Metric, before, after
				if it.State == "completed" && !size(f.Metric) {
					dropped := after < before
					it.Dropped = &dropped
					it.Recurred = it.Recurred || !dropped && after > 0
				}
			}
		}
		if it.Recurred {
			sc.Recurred++
		}
		sc.Items = append(sc.Items, it)
	}
	return sc, nil
}
