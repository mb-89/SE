package issues

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// RetroLabel marks a retro: an issue that checks SE's rules across everything
// closed since the last retro. spec/retro.md has the rules.
const RetroLabel = "se-retro"

// NewMark is what se issue new leaves at the end of every body it writes, so
// the retro can tell an issue it made from one made by hand.
const NewMark = "<!-- se:new -->"

// unattendedMark is in the body of a retro nobody waits for: its box creates
// the findings' issues at once. A retro a person started carries
// <!-- se:retro attended --> instead, and its box stops for the owner.
const unattendedMark = "<!-- se:retro unattended -->"

// Retro is the retro se retro new created.
type Retro struct {
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
	list, err := api[past](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100", s.Repo, RetroLabel), true)
	if err != nil {
		return past{}, false, nil, err
	}
	for _, r := range list {
		if r.PullRequest != nil || r.Number == n {
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
func (s Source) NewRetro(field string, unattended bool) (Retro, error) {
	last, ok, _, err := s.lastRetro(0)
	if err != nil {
		return Retro{}, err
	}
	window := "the repository's whole history: no retro has closed yet"
	r := Retro{Unattended: unattended}
	if ok {
		r.Previous = last.Number
		window = fmt.Sprintf("everything closed since the retro #%d closed, %s", last.Number, last.ClosedAt.UTC().Format(time.RFC3339))
	}
	mode, who := "attended", "A person started it: the box posts its report here and stops for the owner, who decides, then runs `se issue resume`."
	if unattended {
		mode, who = "unattended", "It runs unattended: the box creates the findings' issues at once and closes it."
	}
	feedback := strings.TrimSpace(field)
	switch {
	case feedback == "" && unattended:
		feedback = "None: started unattended."
	case feedback == "":
		feedback = "None given."
	}
	body := fmt.Sprintf("A retro over %s. The rules are spec/retro.md; a box takes it with the retro skill and starts with `se retro collect`.\n\n%s\n\n## Field feedback\n%s\n\n<!-- se:retro %s -->",
		window, who, feedback, mode)
	title := "SE retro " + s.now().UTC().Format("2006-01-02")
	made, _, err := s.create(title, body, 0, nil, []string{Label, RetroLabel})
	if err != nil {
		return Retro{}, err
	}
	r.Issue = made
	return r, nil
}

// Window is what a retro looks at: everything closed after Since, the closing
// of the retro Previous, up to Until. A zero Since is the whole history.
type Window struct {
	Previous int       `yaml:"previous"`
	Since    time.Time `yaml:"since,omitempty"`
	Until    time.Time `yaml:"until"`
}

func (w Window) holds(t time.Time) bool { return !t.IsZero() && t.After(w.Since) && !t.After(w.Until) }

// since is the query that narrows a list to what changed in the window.
func (w Window) since() string {
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

// checkKinds are the rule checks, in the order the report lists them, each
// with the rule it holds the window to.
var checkKinds = []struct{ kind, rule string }{
	{"fixes", "every merged PR said `Fixes #n`"},
	{"ci", "every merged PR had green CI"},
	{"outside-pr", "no commit reached main outside a PR"},
	{"mark", "every `se` issue carries `se issue new`'s mark"},
	{"answers", "every landed issue has landing answers"},
}

// Row is one closed issue of the window: a row of the matrix, with its counts.
type Row struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	// Reason is GitHub's state_reason: completed, not_planned, duplicate.
	Reason string `json:"reason"`
	// Answers are its landing answers, by key; nil where it has none.
	Answers map[string]string `json:"answers,omitempty"`
	// PR is the merged PR that fixed it, 0 for none.
	PR        int `json:"pr,omitempty"`
	Takeovers int `json:"takeovers"`
	Conflicts int `json:"conflicts"`
	Person    int `json:"person"`
	// Minutes is the time from its claim to its PR's merge; -1 unknown.
	Minutes int `json:"minutes"`
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
	Window   Window
	Rows     []Row
	PRs      int
	Commits  int
	Reruns   int
	Checks   []Broken
	Scripts  []Script
	Metrics  Metrics
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
	c := Collected{Retro: n, Attended: !strings.Contains(i.Body, unattendedMark), Window: Window{Until: s.now().UTC().Truncate(time.Second)}}
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

	closed, err := api[past](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100%s", s.Repo, Label, c.Window.since()), true)
	if err != nil {
		return Collected{}, err
	}
	pulls, err := api[merged](s, fmt.Sprintf("repos/%s/pulls?state=closed&base=main&per_page=100", s.Repo), true)
	if err != nil {
		return Collected{}, err
	}
	viaPR := map[string]bool{}
	fixedBy := map[int]merged{}
	var inWindow []merged
	for _, p := range pulls {
		if p.MergedAt == nil {
			continue
		}
		viaPR[p.SHA] = true
		if !c.Window.holds(*p.MergedAt) {
			continue
		}
		inWindow = append(inWindow, p)
		for _, m := range fixesLine.FindAllStringSubmatch(p.Body, -1) {
			fixedBy[atoi(m[1])] = p
		}
	}
	sort.Slice(inWindow, func(a, b int) bool { return inWindow[a].Number < inWindow[b].Number })
	c.PRs = len(inWindow)

	for _, p := range inWindow {
		if fixesLine.FindString(p.Body) == "" {
			c.Checks = append(c.Checks, Broken{"fixes", fmt.Sprintf("PR #%d", p.Number), fmt.Sprintf("%s: its body names no `Fixes #n`", p.Title)})
		}
		red, reruns, err := s.mergedCI(p.Head.SHA)
		if err != nil {
			return Collected{}, err
		}
		c.Reruns += reruns
		if red != "" {
			c.Checks = append(c.Checks, Broken{"ci", fmt.Sprintf("PR #%d", p.Number), fmt.Sprintf("%s: %s", p.Title, red)})
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

	sort.Slice(closed, func(a, b int) bool { return closed[a].Number < closed[b].Number })
	for _, x := range closed {
		if x.PullRequest != nil || x.Number == n || !c.Window.holds(x.ClosedAt) {
			continue
		}
		row, checks, err := s.row(x, fixedBy)
		if err != nil {
			return Collected{}, err
		}
		c.Rows = append(c.Rows, row)
		c.Checks = append(c.Checks, checks...)
	}
	sort.SliceStable(c.Checks, func(a, b int) bool { return kindOrder(c.Checks[a].Kind) < kindOrder(c.Checks[b].Kind) })
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

func kindOrder(kind string) int {
	for k, c := range checkKinds {
		if c.kind == kind {
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
	r := Row{Number: x.Number, Title: x.Title, Reason: x.StateReason, Minutes: -1}
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
	if p, ok := fixedBy[x.Number]; ok {
		r.PR = p.Number
		if landed != nil && !landed.Facts.Claimed.IsZero() {
			r.Minutes = int(p.MergedAt.Sub(landed.Facts.Claimed).Round(time.Minute) / time.Minute)
		}
	}
	parent := x.SubIssues != nil && x.SubIssues.Total > 0
	work := x.StateReason == "completed" && !parent && !x.labelled(RetroLabel)
	if landed != nil {
		r.Answers = landed.Answers
	} else if work {
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
// closed issues, so retros of different sizes compare.
type Metrics map[string]float64

// metricNames are the metrics, in the order the report lists them.
var metricNames = []string{
	"closed", "conflicts", "takeovers", "ci_reruns", "person_flags", "by_hand",
	"conflicts_per_issue", "takeovers_per_issue", "ci_reruns_per_issue", "person_flags_per_issue", "by_hand_per_issue",
	"claim_to_merge_minutes",
}

// lowerIsBetter says which way a metric should move; closed is a size.
func lowerIsBetter(name string) bool { return name != "closed" }

func (c Collected) measure() Metrics {
	m := Metrics{"closed": float64(len(c.Rows)), "ci_reruns": float64(c.Reruns)}
	var minutes []int
	for _, r := range c.Rows {
		m["conflicts"] += float64(r.Conflicts)
		m["takeovers"] += float64(r.Takeovers)
		m["person_flags"] += float64(r.Person)
		if r.Answers != nil && !nothing(r.Answers["by-hand"]) {
			m["by_hand"]++
		}
		if r.Minutes >= 0 {
			minutes = append(minutes, r.Minutes)
		}
	}
	for _, name := range []string{"conflicts", "takeovers", "ci_reruns", "person_flags", "by_hand"} {
		m[name+"_per_issue"] = 0
		if len(c.Rows) > 0 {
			m[name+"_per_issue"] = round2(m[name] / float64(len(c.Rows)))
		}
	}
	m["claim_to_merge_minutes"] = float64(median(minutes))
	return m
}

func round2(x float64) float64 { return float64(int(x*100+0.5)) / 100 }

func median(xs []int) int {
	if len(xs) == 0 {
		return 0
	}
	sort.Ints(xs)
	return xs[len(xs)/2]
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
	// Dropped says whether its metric moved the right way; nil without one.
	Dropped *bool `yaml:"dropped,omitempty"`
}

// score reads how each finding of the previous report fared: did its issue
// close, did the rule check it named break again, did its metric drop.
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
				dropped := after < before
				if !lowerIsBetter(f.Metric) {
					dropped = after > before
				}
				it.Dropped = &dropped
				it.Recurred = it.Recurred || !dropped && after > 0
			}
		}
		if it.Recurred {
			sc.Recurred++
		}
		sc.Items = append(sc.Items, it)
	}
	return sc, nil
}
