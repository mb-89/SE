package issues

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// RetroLabel and OverhaulLabel mark the issues that run a retro and an overhaul.
const (
	RetroLabel    = "se-retro"
	OverhaulLabel = "se-overhaul"
)

// Window chooses the closed issues se briefing tells of: those closed since
// Since, or the Last most recently closed; with neither, those closed in the
// last day or the last DefaultLast, whichever are more.
type Window struct {
	Since time.Time
	Last  int
}

// DefaultLast is how many closed issues the default window holds at least.
const DefaultLast = 10

// Briefed are the documents a briefing links, relative to the checkout.
var Briefed = []string{"spec/principles.md", "spec/issues.md", "CLAUDE.md"}

// Briefing is where SE stands, as se briefing tells it.
type Briefing struct {
	Repo string    `json:"repo"`
	At   time.Time `json:"at"`
	// About is what SE is: the README's first sentences, and the documents to read.
	About About `json:"about"`
	// Pending is what waits on the person, from every registered source.
	Pending []Pending `json:"pending"`
	// Window says which closed issues Happened holds.
	Window   string   `json:"window"`
	Happened []Closed `json:"happened"`
	// Retro is the last closed retro; nil where none has run.
	Retro *Retro `json:"retro,omitempty"`
	// InFlight is the claimed leaves and their PRs; Findings is what se fleet
	// check reports.
	InFlight []Flight  `json:"in_flight"`
	Findings []Finding `json:"findings"`
	// Next is what se issue next would take; nil where nothing is ready.
	Next   *Issue `json:"next,omitempty"`
	Counts Counts `json:"counts"`
}

// About is what SE is.
type About struct {
	Lines []string `json:"lines"`
	Links []Link   `json:"links"`
}

// Link is one document a briefing points to.
type Link struct {
	Path string `json:"path"`
	URL  string `json:"url"`
}

// Closed is one issue closed in the window.
type Closed struct {
	Number int       `json:"number"`
	Title  string    `json:"title"`
	URL    string    `json:"url"`
	At     time.Time `json:"closed_at"`
	// PR is the PR that landed it, from its issue branch; 0 where none did.
	PR    int    `json:"pr,omitempty"`
	PRURL string `json:"pr_url,omitempty"`
	// Done is the landing answer done, where it was landed with answers.
	Done string `json:"done,omitempty"`
	// Run is "retro" or "overhaul" for an issue that ran one.
	Run        string `json:"run,omitempty"`
	NotPlanned bool   `json:"not_planned,omitempty"`
	// Person is set where it went to a person on its way.
	Person bool `json:"person,omitempty"`
}

// Retro is the last closed retro.
type Retro struct {
	Number int       `json:"number"`
	Title  string    `json:"title"`
	URL    string    `json:"url"`
	At     time.Time `json:"closed_at"`
	// Headlines are the first findings of its closing comment.
	Headlines []string `json:"headlines"`
}

// Flight is one claimed leaf.
type Flight struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	URL    string `json:"url"`
	PR     int    `json:"pr,omitempty"`
	PRURL  string `json:"pr_url,omitempty"`
	// State is where its PR stands: CI, conflicts, auto-merge; or that it has none.
	State string `json:"state"`
}

// Counts is how the open issues at the top stand, and how many are inside trees.
type Counts struct {
	Ready   int `json:"ready"`
	Claimed int `json:"claimed"`
	Blocked int `json:"blocked"`
	InTrees int `json:"in_trees"`
}

// Briefing reads GitHub and the checkout dir and says where SE stands. It writes
// nothing but what every se issue command writes.
func (s Source) Briefing(dir string, w Window) (Briefing, error) {
	b := Briefing{Repo: s.Repo, At: s.now().UTC().Truncate(time.Second), InFlight: []Flight{}}
	b.About = about(dir, s.Repo)
	all, t, err := s.survey()
	if err != nil {
		return Briefing{}, err
	}
	waiting, err := s.waiting(all, t)
	if err != nil {
		return Briefing{}, err
	}
	if b.Pending, err = pending(Open{Repo: s.Repo, Waiting: waiting, t: t}); err != nil {
		return Briefing{}, err
	}
	if b.InFlight, err = s.inFlight(all); err != nil {
		return Briefing{}, err
	}
	found, err := s.Check()
	if err != nil {
		return Briefing{}, err
	}
	b.Findings = append([]Finding{}, found...)
	if order := takeOrder(all, 0); len(order) > 0 {
		b.Next = &order[0].Issue
	}
	for _, st := range all {
		switch {
		case st.Above != 0:
			b.Counts.InTrees++
		case st.claimed:
			b.Counts.Claimed++
		case st.Ready():
			b.Counts.Ready++
		default:
			b.Counts.Blocked++
		}
	}
	closed, err := api[issue](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100", s.Repo, Label), true)
	if err != nil {
		return Briefing{}, err
	}
	var done []closedIssue
	for _, i := range closed {
		if i.PullRequest == nil {
			done = append(done, closedIssue{i, i.ClosedAt})
		}
	}
	sort.Slice(done, func(a, c int) bool {
		if !done[a].at.Equal(done[c].at) {
			return done[a].at.After(done[c].at)
		}
		return done[a].Number > done[c].Number
	})
	var in []closedIssue
	in, b.Window = s.window(done, w)
	b.Happened = []Closed{}
	for _, c := range in {
		got, err := s.closedOf(c)
		if err != nil {
			return Briefing{}, err
		}
		b.Happened = append(b.Happened, got)
	}
	for _, c := range done {
		if c.labelled(RetroLabel) {
			if b.Retro, err = s.retro(c); err != nil {
				return Briefing{}, err
			}
			break
		}
	}
	return b, nil
}

// closedIssue is a closed issue and when it closed.
type closedIssue struct {
	issue
	at time.Time
}

// window picks the closed issues, newest first, that w chooses, and says which.
func (s Source) window(done []closedIssue, w Window) ([]closedIssue, string) {
	since := func(t time.Time) []closedIssue {
		var in []closedIssue
		for _, c := range done {
			if !c.at.Before(t) {
				in = append(in, c)
			}
		}
		return in
	}
	last := func(n int) []closedIssue { return done[:min(n, len(done))] }
	switch {
	case !w.Since.IsZero():
		return since(w.Since), "closed since " + w.Since.UTC().Format(time.RFC3339)
	case w.Last > 0:
		return last(w.Last), fmt.Sprintf("the last %d closed", w.Last)
	}
	day := since(s.now().Add(-24 * time.Hour))
	if len(day) >= DefaultLast {
		return day, "closed in the last day"
	}
	return last(DefaultLast), fmt.Sprintf("the last %d closed", DefaultLast)
}

// closedOf tells of one closed issue: its PR, its landing answer done, and
// whether it ran a retro or an overhaul or went to a person.
func (s Source) closedOf(c closedIssue) (Closed, error) {
	out := Closed{Number: c.Number, Title: c.Title, URL: c.URL, At: c.at, NotPlanned: c.StateReason == "not_planned"}
	switch {
	case c.labelled(RetroLabel):
		out.Run = "retro"
	case c.labelled(OverhaulLabel):
		out.Run = "overhaul"
	}
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, c.Number), true)
	if err != nil {
		return Closed{}, err
	}
	for _, m := range comments {
		if l, ok, err := ParseLanding(m.Body); ok && err == nil {
			out.Done = strings.TrimSpace(l.Answers["done"])
		}
		for _, got := range mark.FindAllStringSubmatch(m.Body, -1) {
			out.Person = out.Person || got[1] == "person"
		}
	}
	owner, _, _ := strings.Cut(s.Repo, "/")
	pulls, err := api[struct {
		Number int     `json:"number"`
		URL    string  `json:"html_url"`
		Merged *string `json:"merged_at"`
	}](s, fmt.Sprintf("repos/%s/pulls?head=%s:%s&base=main&state=closed&per_page=100", s.Repo, owner, Branch(c.Number)), true)
	if err != nil {
		return Closed{}, err
	}
	for _, p := range pulls {
		if out.PR == 0 || p.Merged != nil {
			out.PR, out.PRURL = p.Number, p.URL
		}
		if p.Merged != nil {
			break
		}
	}
	return out, nil
}

// Headlines is how many findings of the last retro a briefing shows.
const Headlines = 5

// retro tells of the last closed retro: the first findings of its closing
// comment, its bullet points, or else its first lines.
func (s Source) retro(c closedIssue) (*Retro, error) {
	r := &Retro{Number: c.Number, Title: c.Title, URL: c.URL, At: c.at, Headlines: []string{}}
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, c.Number), true)
	if err != nil || len(comments) == 0 {
		return r, err
	}
	var bullets, lines []string
	for _, l := range strings.Split(comments[len(comments)-1].Body, "\n") {
		l = strings.TrimSpace(l)
		switch {
		case l == "" || strings.HasPrefix(l, "<!--") || strings.HasPrefix(l, "```"):
		case strings.HasPrefix(l, "- ") || strings.HasPrefix(l, "* "):
			bullets = append(bullets, strings.TrimSpace(l[2:]))
		default:
			lines = append(lines, strings.TrimLeft(l, "# "))
		}
	}
	if len(bullets) == 0 {
		bullets = lines
	}
	r.Headlines = append(r.Headlines, bullets[:min(Headlines, len(bullets))]...)
	return r, nil
}

// inFlight is every claimed leaf, with where its open PR stands.
func (s Source) inFlight(all []Status) ([]Flight, error) {
	pulls, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls?base=main&state=open&per_page=100", s.Repo), true)
	if err != nil {
		return nil, err
	}
	byRef := map[string]openPull{}
	for _, p := range pulls {
		byRef[p.Head.Ref] = p
	}
	out := []Flight{}
	for _, st := range all {
		if !st.claimed {
			continue
		}
		f := Flight{Number: st.Number, Title: st.Title, URL: st.URL, State: "no PR yet"}
		if st.Stuck {
			f.State += ", stuck: " + st.since()
		}
		if p, ok := byRef[Branch(st.Number)]; ok {
			if f.State, err = s.pullState(p); err != nil {
				return nil, err
			}
			f.PR, f.PRURL = p.Number, p.URL
		}
		out = append(out, f)
	}
	return out, nil
}

// pullState says where an open PR stands: whether it conflicts with main,
// its CI on its latest commit, and its auto-merge.
func (s Source) pullState(p openPull) (string, error) {
	p, err := s.mergeability(p)
	if err != nil {
		return "", err
	}
	var parts []string
	if p.dirty() {
		parts = append(parts, "conflicts with main")
	}
	red, running, err := s.checks(p.Head.SHA)
	if err != nil {
		return "", err
	}
	switch {
	case len(red) > 0:
		parts = append(parts, "CI red: "+strings.Join(red, ", "))
	case running:
		parts = append(parts, "CI running")
	default:
		parts = append(parts, "CI green")
	}
	if p.AutoMerge != nil {
		parts = append(parts, "auto-merge on")
	} else {
		parts = append(parts, "auto-merge off")
	}
	return strings.Join(parts, ", "), nil
}

// AboutSentences is how many of the README's first sentences say what SE is.
const AboutSentences = 4

// about is what SE is: the first sentences of the README's first paragraph,
// and the documents a briefing links.
func about(dir, repo string) About {
	a := About{Lines: []string{}}
	for _, p := range Briefed {
		a.Links = append(a.Links, Link{Path: p, URL: fmt.Sprintf("https://github.com/%s/blob/main/%s", repo, p)})
	}
	data, err := os.ReadFile(filepath.Join(dir, "README.md"))
	if err != nil {
		return a
	}
	var para []string
	for _, l := range strings.Split(string(data), "\n") {
		l = strings.TrimSpace(l)
		if l == "" && len(para) > 0 {
			break
		}
		// The title above the first paragraph is no part of it.
		if l != "" && (len(para) > 0 || !strings.HasPrefix(l, "#")) {
			para = append(para, l)
		}
	}
	text := strings.Join(para, " ")
	for text != "" && len(a.Lines) < AboutSentences {
		end := strings.Index(text, ". ")
		if end < 0 {
			a.Lines = append(a.Lines, text)
			break
		}
		a.Lines = append(a.Lines, text[:end+1])
		text = strings.TrimSpace(text[end+2:])
	}
	return a
}
