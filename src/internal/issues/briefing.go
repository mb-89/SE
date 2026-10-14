package issues

import (
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
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
	// Next is what se issue pull would take; nil where nothing is ready.
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
// nothing but what every se issue command writes. It reads everything first,
// each thing once and independent reads in parallel, then judges what it read.
func (s Source) Briefing(dir string, w Window) (Briefing, error) {
	b := Briefing{Repo: s.Repo, At: s.now().UTC().Truncate(time.Second), InFlight: []Flight{}}
	b.About = about(s.Disk, dir, s.Repo)
	var (
		all     []Status
		t       tree
		done    []closedIssue
		in      []closedIssue
		retro   *closedIssue
		pulls   []closedPull
		history []comment
	)
	if err := parallel([]func() error{
		func() (err error) { all, t, err = s.survey(); return err },
		// The closed issues, the window, and the comments of every issue
		// told of, read at once: every one was written after the oldest of
		// those issues was created.
		func() error {
			closed, err := api[issue](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100", s.Repo, Label), true)
			if err != nil {
				return err
			}
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
			in, b.Window = s.window(done, w)
			told := in
			for k := range done {
				if done[k].labelled(RetroLabel) {
					retro = &done[k]
					told = append(append([]closedIssue{}, in...), *retro)
					break
				}
			}
			if len(told) == 0 {
				return nil
			}
			since := told[0].Created
			for _, c := range told {
				if c.Created.Before(since) {
					since = c.Created
				}
			}
			history, err = pages[comment](s, fmt.Sprintf("repos/%s/issues/comments?since=%s&per_page=%d", s.Repo, since.UTC().Format(time.RFC3339), PerPage))
			return err
		},
		func() (err error) {
			pulls, err = pages[closedPull](s, fmt.Sprintf("repos/%s/pulls?base=main&state=closed&per_page=%d", s.Repo, PerPage))
			return err
		},
	}); err != nil {
		return Briefing{}, err
	}
	// The PRs from this repository's own branches, newest first.
	t.shut = map[string][]closedPull{}
	for _, p := range pulls {
		if p.Head.Repo != nil && p.Head.Repo.FullName == s.Repo {
			t.shut[p.Head.Ref] = append(t.shut[p.Head.Ref], p)
		}
	}
	if err := parallel([]func() error{
		func() (err error) { b.InFlight, err = s.inFlight(all, t); return err },
		func() (err error) { b.Findings, err = s.check(all, t); return err },
	}); err != nil {
		return Briefing{}, err
	}
	comments := map[int][]comment{}
	for _, m := range history {
		n := atoi(m.IssueURL[strings.LastIndex(m.IssueURL, "/")+1:])
		comments[n] = append(comments[n], m)
	}
	for _, cs := range comments {
		sort.Slice(cs, func(a, c int) bool { return cs[a].ID < cs[c].ID })
	}
	b.Findings = append([]Finding{}, b.Findings...)
	var err error
	if b.Pending, err = pending(Open{Repo: s.Repo, Waiting: waiting(all, t), t: t}); err != nil {
		return Briefing{}, err
	}
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
	b.Happened = []Closed{}
	for _, c := range in {
		b.Happened = append(b.Happened, closedOf(c, comments[c.Number], t.shut[Branch(c.Number)]))
	}
	if retro != nil {
		b.Retro = retroOf(*retro, comments[retro.Number])
	}
	return b, nil
}

// closedPull is the part of GitHub's pull request object a briefing reads.
type closedPull struct {
	Number int     `json:"number"`
	URL    string  `json:"html_url"`
	Merged *string `json:"merged_at"`
	Head   struct {
		Ref  string `json:"ref"`
		Repo *struct {
			FullName string `json:"full_name"`
		} `json:"repo"`
	} `json:"head"`
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

// closedOf tells of one closed issue from its comments and the closed PRs of
// its branch, newest first: its PR, its landing answer done, and whether it
// ran a retro or an overhaul or went to a person.
func closedOf(c closedIssue, comments []comment, pulls []closedPull) Closed {
	out := Closed{Number: c.Number, Title: c.Title, URL: c.URL, At: c.at, NotPlanned: c.StateReason == "not_planned"}
	switch {
	case c.labelled(RetroLabel):
		out.Run = "retro"
	case c.labelled(OverhaulLabel):
		out.Run = "overhaul"
	}
	for _, m := range comments {
		if l, ok, err := ParseLanding(m.Body); ok && err == nil {
			out.Done = strings.TrimSpace(l.Answers["done"])
		}
		for _, got := range mark.FindAllStringSubmatch(m.Body, -1) {
			out.Person = out.Person || got[1] == "person"
		}
	}
	for _, p := range pulls {
		if out.PR == 0 || p.Merged != nil {
			out.PR, out.PRURL = p.Number, p.URL
		}
		if p.Merged != nil {
			break
		}
	}
	return out
}

// Headlines is how many findings of the last retro a briefing shows.
const Headlines = 5

// retroOf tells of the last closed retro from its comments: the first
// findings of its closing comment, its bullet points, or else its first lines.
func retroOf(c closedIssue, comments []comment) *Retro {
	r := &Retro{Number: c.Number, Title: c.Title, URL: c.URL, At: c.at, Headlines: []string{}}
	if len(comments) == 0 {
		return r
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
	return r
}

// inFlight is every claimed leaf, with where its open PR stands.
func (s Source) inFlight(all []Status, t tree) ([]Flight, error) {
	byRef := toMain(t.pulls)
	var claimed []Status
	for _, st := range all {
		if st.claimed {
			claimed = append(claimed, st)
		}
	}
	return each(len(claimed), func(k int) (Flight, error) {
		st := claimed[k]
		f := Flight{Number: st.Number, Title: st.Title, URL: st.URL, State: "no PR yet"}
		if st.Stuck {
			f.State += ", stuck: " + st.since()
		}
		if p, ok := byRef[Branch(st.Number)]; ok {
			state, err := s.pullState(p, t.runs)
			if err != nil {
				return Flight{}, err
			}
			f.State, f.PR, f.PRURL = state, p.Number, p.URL
		}
		return f, nil
	})
}

// pullState says where an open PR stands: whether it conflicts with main,
// its CI on its latest commit, and its auto-merge.
func (s Source) pullState(p openPull, runs *runs) (string, error) {
	p, err := s.mergeability(p)
	if err != nil {
		return "", err
	}
	var parts []string
	if p.dirty() {
		parts = append(parts, "conflicts with main")
	}
	red, running, err := runs.checks(s, p.Head.SHA)
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
func about(d disk.Disk, dir, repo string) About {
	a := About{Lines: []string{}}
	for _, p := range Briefed {
		a.Links = append(a.Links, Link{Path: p, URL: fmt.Sprintf("https://github.com/%s/blob/main/%s", repo, p)})
	}
	data, err := d.ReadFile(filepath.Join(dir, "README.md"))
	if err != nil {
		return a
	}
	var para []string
	for _, l := range strings.Split(string(data), "\n") {
		l = strings.TrimSpace(l)
		if l == "" && len(para) > 0 {
			break
		}
		// The title and the reader line above the first paragraph are no part of it.
		if l != "" && (len(para) > 0 || !strings.HasPrefix(l, "#") && !strings.HasPrefix(l, "Reader: ")) {
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
