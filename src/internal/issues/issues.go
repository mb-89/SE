// Package issues picks the fleet's next GitHub issue and claims it. The rules
// it follows live in spec/issues.md; this is their one implementation.
package issues

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// Label marks an issue as the fleet's work.
const Label = "se"

// ReviewLabel marks a parent that is reviewed once its sub-issues are closed,
// so it never closes by itself.
const ReviewLabel = "se-review"

// FinalLabel marks an issue on its last attempt: one a review filed for a
// finding, or one taken over once already. A final issue is never superseded
// again; stuck again, it is taken over again, and a re-review that finds its
// problem again accepts the repeat.
const FinalLabel = "se-final"

// Issue is one fleet issue.
type Issue struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	Body   string `json:"body"`
	URL    string `json:"url"`
	// Parent is true for an issue with sub-issues: it holds no work of its
	// own, and taking it means coordinating them.
	Parent bool `json:"parent,omitempty"`
	// Retro is true for an issue labelled se-retro: the agent se:retro does it.
	Retro bool `json:"retro,omitempty"`
	// Overhaul is true for an issue labelled se-overhaul: the agent se:overhaul
	// does it.
	Overhaul bool `json:"overhaul,omitempty"`
	// Takeover is set for a leaf a take takes over, stuck for the first time
	// or its PR in conflict with main: taking it continues its branch and PR
	// as they stand.
	Takeover *Takeover `json:"takeover,omitempty"`
	// Blocks names the open issues it blocks, where a take read them: what
	// is left of it may hold up those that need it (se issue new --blocks).
	Blocks []int `json:"blocks,omitempty"`
	// id is GitHub's id of an issue se just created, which a link takes.
	id int64
}

// Branch is the branch whose presence on origin claims issue n.
func Branch(n int) string { return fmt.Sprintf("issue-%d", n) }

// Source reads one repository's issues through GitHub.
type Source struct {
	// Repo is OWNER/NAME.
	Repo   string
	GitHub github.GitHub
	// Clock is the time leases, windows and stamps are read against.
	Clock clock.Clock
	// Disk is what checkouts' files are read from.
	Disk disk.Disk
	// Proc runs git in the checkouts the source claims, picks up and lands from.
	Proc proc.Procs
	// Waits hears what the source waits on, and for how long, before each
	// wait, so the person running it is not left waiting blind.
	Waits func(note string)
	// Box is the session of the box that claims: each claim records it, so
	// the fan-out counts each alive box's claims. Empty records nothing.
	Box string
	// Worktrees makes a take at the top check nothing out: the box hands
	// the issue to a sub-agent in its own worktree, and a take refuses
	// where the box runs its cap of sub-agents already.
	Worktrees bool
	// Parallel is the cap of sub-agents one box runs, fleet.box/config/parallel;
	// zero is its built-in value, Parallel.
	Parallel int
	// Config is the issue work's config, issues/config/<key>, as Configured
	// reads it; nil runs on the built-in values.
	Config *Settings
}

func (s Source) now() time.Time { return s.Clock.Now() }

// sleep waits d, after telling Waits what for.
func (s Source) sleep(d time.Duration, what string) {
	if s.Waits != nil {
		s.Waits(fmt.Sprintf("waiting %s for %s", d, what))
	}
	s.Clock.Sleep(d)
}

// issue is the part of GitHub's issue object the rules read.
type issue struct {
	ID          int64  `json:"id"`
	Number      int    `json:"number"`
	Title       string `json:"title"`
	Body        string `json:"body"`
	State       string `json:"state"`
	StateReason string `json:"state_reason"`
	// ClosedAt is when a closed issue closed; zero while it is open.
	ClosedAt time.Time `json:"closed_at"`
	// Created is when it was opened.
	Created time.Time `json:"created_at"`
	URL     string    `json:"html_url"`
	// RepositoryURL names the issue's repository, which a blocker may be outside.
	RepositoryURL string           `json:"repository_url"`
	PullRequest   *json.RawMessage `json:"pull_request"`
	// SubIssues is GitHub's count of the issue's sub-issues; absent, it has none.
	SubIssues *struct {
		Total     int `json:"total"`
		Completed int `json:"completed"`
	} `json:"sub_issues_summary"`
	Labels []struct {
		Name string `json:"name"`
	} `json:"labels"`
}

func (i issue) labelled(name string) bool {
	for _, l := range i.Labels {
		if l.Name == name {
			return true
		}
	}
	return false
}

// api reads a GitHub path, every page of it where list is set, into out.
func api[T any](s Source, path string, list bool) ([]T, error) {
	if !list {
		out, err := s.GitHub.Get(path)
		if err != nil {
			return nil, err
		}
		var one T
		if err := json.Unmarshal(out, &one); err != nil {
			return nil, fmt.Errorf("gh api %s: %v", path, err)
		}
		return []T{one}, nil
	}
	out, err := s.GitHub.List(path)
	if err != nil {
		return nil, err
	}
	var all []T
	if err := json.Unmarshal(out, &all); err != nil {
		return nil, fmt.Errorf("gh api %s: %v", path, err)
	}
	return all, nil
}

// PerPage is how many items pages asks for on each page.
const PerPage = 100

// pages reads a list path, which asks per_page=PerPage, page by page until
// a page comes back short, asking for page=k itself on the repos/ path, as
// the real GitHub's List does for api: GitHub's next links name
// repositories/{id} for some lists, which the box proxy refuses.
func pages[T any](s Source, path string) ([]T, error) {
	var all []T
	for k := 1; ; k++ {
		page, err := api[[]T](s, fmt.Sprintf("%s&page=%d", path, k), false)
		if err != nil {
			return nil, err
		}
		all = append(all, page[0]...)
		if len(page[0]) < PerPage {
			return all, nil
		}
	}
}

// Status is where one open fleet issue stands.
type Status struct {
	Issue
	// Why is empty for a ready issue, else what holds it: "claimed by
	// issue-7", "blocked by #3, #4", "#2 is blocked by #3" (an ancestor's
	// blocker), "waits on a person", "#5 waits on a person" (a parent whose
	// tree holds it), "nothing inside is ready" (a parent).
	Why string `json:"why,omitempty"`
	// Above is the open fleet issue this one is a sub-issue of; 0 at the top.
	Above int `json:"above,omitempty"`
	// Review is true for a parent labelled se-review whose sub-issues are all
	// closed: it waits for its review, which is not work, but its coordinator
	// starts the reviewer.
	Review bool `json:"review,omitempty"`
	// Stuck is set for a claimed leaf nothing was pushed to for longer than
	// the lease; Takeovers is its last takeover round, which only settles
	// two boxes racing for one round (the label se-final is the record of a
	// takeover), and Since is when its
	// branch last saw a push or a takeover.
	Stuck     bool      `json:"stuck,omitempty"`
	Takeovers int       `json:"takeovers,omitempty"`
	Since     time.Time `json:"-"`
	// Final is set for an issue labelled se-final: on its last attempt.
	Final bool `json:"final,omitempty"`
	// Person is set for an issue labelled se-person; Reason says why.
	Person bool   `json:"person,omitempty"`
	Reason string `json:"reason,omitempty"`
	// waits is the lowest issue in its tree, itself included, that waits on
	// a person; urgent is set where taking it continues stuck work.
	waits  int
	urgent bool
	// claimed is true for a leaf whose branch exists on origin; pushed is
	// when its branch last saw a push, zero where GitHub keeps no record.
	claimed bool
	pushed  time.Time
}

// Ready says whether the issue may be taken as new work: a ready leaf is
// work, a ready parent has work or a review inside it, or is ready for review
// itself.
func (s Status) Ready() bool { return s.Why == "" }

// Takeable says whether a take may have it: ready, or a leaf stuck for the
// first time, which is taken over.
func (s Status) Takeable() bool { return s.Ready() || s.Takeover != nil }

// tree is the open fleet issues and their sub-issues.
type tree struct {
	byNum map[int]issue
	// subs is each parent's sub-issues, open and closed.
	subs map[int][]issue
	// above is each open fleet issue's parent, where that is an open fleet issue.
	above map[int]int
	// closed is the parents this read closed.
	closed map[int]bool
	// What survey reads with it, once, for everything that judges the fleet:
	// refs is the issue-<n> branches on origin, deps each open fleet issue's
	// "blocked by" links, open or closed, and pulls the open PRs, any base,
	// read where an issue branch exists.
	refs  []ref
	deps  map[int][]issue
	pulls []openPull
	// runs is the check runs read so far, by commit: each is read once.
	runs *runs
	// shut is the closed PRs into main from this repository's branches, by
	// branch, newest first, where a briefing read them all; nil otherwise.
	shut map[string][]closedPull
}

func (t tree) numbers() []int {
	var ns []int
	for n := range t.byNum {
		ns = append(ns, n)
	}
	sort.Ints(ns)
	return ns
}

func (t tree) depth(n int) int {
	d := 0
	for p, ok := t.above[n]; ok && d <= len(t.above); p, ok = t.above[p] {
		d++
	}
	return d
}

// load reads the open fleet issues with their sub-issues, then closes every
// parent whose sub-issues are all closed, deepest first, so a parent its
// closing completes closes too. A parent labelled se-review never closes here.
// The reads more makes from the list run beside the sub-issues' reads.
func (s Source) load(more func(t tree) []func() error) (tree, error) {
	list, err := api[issue](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=open&per_page=100", s.Repo, Label), true)
	if err != nil {
		return tree{}, err
	}
	t := tree{byNum: map[int]issue{}, subs: map[int][]issue{}, above: map[int]int{}, closed: map[int]bool{}}
	for _, i := range list {
		if i.PullRequest == nil {
			t.byNum[i.Number] = i
		}
	}
	var parents []int
	for _, n := range t.numbers() {
		if t.parent(n) {
			parents = append(parents, n)
		}
	}
	subs := make([][]issue, len(parents))
	var reads []func() error
	for k, n := range parents {
		reads = append(reads, func() (err error) {
			subs[k], err = api[issue](s, fmt.Sprintf("repos/%s/issues/%d/sub_issues?per_page=100", s.Repo, n), true)
			return err
		})
	}
	if more != nil {
		reads = append(reads, more(t)...)
	}
	if err := parallel(reads); err != nil {
		return tree{}, err
	}
	for k, n := range parents {
		t.subs[n] = subs[k]
		for _, c := range subs[k] {
			if _, ok := t.byNum[c.Number]; ok {
				t.above[c.Number] = n
			}
		}
	}
	sort.SliceStable(parents, func(a, b int) bool { return t.depth(parents[a]) > t.depth(parents[b]) })
	for _, n := range parents {
		if t.byNum[n].labelled(ReviewLabel) || !t.done(n) {
			continue
		}
		if err := s.closeParent(n); err != nil {
			return tree{}, err
		}
		t.closed[n] = true
		delete(t.byNum, n)
	}
	return t, nil
}

// parent says whether open fleet issue n has sub-issues, by GitHub's count.
func (t tree) parent(n int) bool {
	i := t.byNum[n]
	return i.SubIssues != nil && i.SubIssues.Total > 0
}

// done says whether every sub-issue of n is closed.
func (t tree) done(n int) bool {
	for _, c := range t.subs[n] {
		if c.State == "open" && !t.closed[c.Number] {
			return false
		}
	}
	return true
}

// closeParent closes a parent whose sub-issues are all closed, saying why.
func (s Source) closeParent(n int) error {
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", fmt.Sprintf("All sub-issues of #%d are closed, so it closes by itself.", n))); err != nil {
		return fmt.Errorf("closing parent #%d: %w", n, err)
	}
	if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", "completed")); err != nil {
		return fmt.Errorf("closing parent #%d: %w", n, err)
	}
	return nil
}

// CloseParents closes every open parent whose sub-issues are all closed,
// deepest first, except those labelled se-review. Every se issue command does
// this first.
func (s Source) CloseParents() error {
	_, err := s.load(nil)
	return err
}

// Survey reads every open fleet issue and says where each stands, lowest
// number first.
func (s Source) Survey() ([]Status, error) {
	all, _, err := s.survey()
	return all, err
}

func (s Source) survey() ([]Status, tree, error) {
	// The input phase: every read the judging below needs, each once, in
	// parallel, each as soon as what it needs is read. The writes, closing
	// parents and the sweep's, come after it, in order.
	deps := map[int]*[]issue{}
	marked := map[int]*marks{}
	leased := map[int]*Status{}
	claimed := map[string]bool{}
	var refs []ref
	var pulls []openPull
	t, err := s.load(func(t tree) []func() error {
		ns := t.numbers()
		for _, n := range ns {
			deps[n], marked[n], leased[n] = &[]issue{}, &marks{}, &Status{}
		}
		reads := []func() error{
			// The branches, and what only issue branches need: the open PRs
			// and each claimed leaf's lease.
			func() (err error) {
				if refs, err = api[ref](s, fmt.Sprintf("repos/%s/git/matching-refs/heads/issue-", s.Repo), true); err != nil || len(refs) == 0 {
					return err
				}
				for _, r := range refs {
					claimed[strings.TrimPrefix(r.Ref, "refs/heads/")] = true
				}
				reads := []func() error{func() (err error) {
					pulls, err = api[openPull](s, fmt.Sprintf("repos/%s/pulls?state=open&per_page=100", s.Repo), true)
					return err
				}}
				for _, n := range ns {
					if !t.parent(n) && claimed[Branch(n)] && !t.byNum[n].labelled(PersonLabel) {
						reads = append(reads, func() error {
							leased[n].Number = n
							return s.lease(leased[n])
						})
					}
				}
				return parallel(reads)
			},
		}
		for _, n := range ns {
			reads = append(reads, func() (err error) {
				*deps[n], err = api[issue](s, fmt.Sprintf("repos/%s/issues/%d/dependencies/blocked_by?per_page=100", s.Repo, n), true)
				return err
			})
			if t.byNum[n].labelled(PersonLabel) {
				reads = append(reads, func() (err error) {
					*marked[n], err = s.marks(n)
					return err
				})
			}
		}
		return reads
	})
	if err != nil {
		return nil, tree{}, err
	}
	t.refs, t.pulls, t.runs, t.deps = refs, pulls, &runs{read: map[string]*checked{}}, map[int][]issue{}
	ns := t.numbers()
	for _, n := range ns {
		t.deps[n] = *deps[n]
	}
	// held names the open blockers of n, or else of its nearest ancestor that has any.
	held := func(n int) string {
		for m := n; ; {
			if b := t.openBlockers(m); len(b) > 0 {
				names := make([]string, len(b))
				for k, x := range b {
					names[k] = "#" + strconv.Itoa(x)
				}
				if m == n {
					return "blocked by " + strings.Join(names, ", ")
				}
				return fmt.Sprintf("#%d is blocked by %s", m, strings.Join(names, ", "))
			}
			p, ok := t.above[m]
			if !ok {
				return ""
			}
			m = p
		}
	}
	byNum := map[int]*Status{}
	var out []*Status
	for _, n := range ns {
		i := t.byNum[n]
		_, parent := t.subs[n]
		st := &Status{Issue: Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL, Parent: parent, Retro: i.labelled(RetroLabel), Overhaul: i.labelled(OverhaulLabel)}, Above: t.above[n], Final: i.labelled(FinalLabel)}
		switch {
		case i.labelled(PersonLabel):
			st.Person, st.Why = true, "waits on a person"
			if st.Reason = marked[n].reason; st.Reason == "" {
				st.Reason = firstParagraph(i.Body)
			}
		case !parent && claimed[Branch(n)]:
			// A claim waiting on its blockers is not stuck; once they close,
			// its old push makes it stuck at once, and the next box takes it
			// over afresh.
			if why := held(n); why != "" {
				st.Why = Branch(n) + " waits: " + why
				break
			}
			st.Why, st.claimed = "claimed by "+Branch(n), true
			l := leased[n]
			st.Since, st.pushed, st.Takeovers, st.Stuck = l.Since, l.pushed, l.Takeovers, l.Stuck
			// A stuck claim, final or not, is a takeover candidate: the
			// survey reads and writes nothing.
			if st.Stuck {
				st.Takeover = &Takeover{Count: st.Takeovers + 1, Stale: st.since()}
				st.urgent = true
				st.Why += ", stuck: " + st.since()
			}
		default:
			st.Why = held(n)
		}
		if parent && st.Why == "" && t.done(n) {
			st.Review = true
		}
		byNum[n] = st
		out = append(out, st)
	}
	// A tree holding an issue that waits on a person is never offered.
	var waits func(n int) int
	waits = func(n int) int {
		w := 0
		if byNum[n].Person {
			w = n
		}
		for _, c := range t.subs[n] {
			if _, ok := byNum[c.Number]; ok {
				if x := waits(c.Number); x != 0 && (w == 0 || x < w) {
					w = x
				}
			}
		}
		return w
	}
	for _, st := range out {
		if st.waits = waits(st.Number); st.waits != 0 && st.Why == "" {
			st.Why = fmt.Sprintf("#%d waits on a person", st.waits)
		}
	}
	// A parent is ready while a leaf anywhere inside it may be taken, or a
	// parent inside it is ready for review, and urgent while a leaf inside is
	// stuck.
	var inside func(n int, urgent bool) bool
	inside = func(n int, urgent bool) bool {
		for _, c := range t.subs[n] {
			st, ok := byNum[c.Number]
			if !ok {
				continue
			}
			if st.Parent && st.Why == "" && (st.Review && !urgent || inside(c.Number, urgent)) {
				return true
			}
			if !st.Parent && st.Takeable() && (!urgent || st.Takeover != nil) {
				return true
			}
		}
		return false
	}
	all := make([]Status, len(out))
	for k, st := range out {
		if st.Parent && st.Why == "" && !st.Review {
			if !inside(st.Number, false) {
				st.Why = "nothing inside is ready"
			}
			st.urgent = inside(st.Number, true)
		}
		all[k] = *st
	}
	return all, t, nil
}

// firstParagraph is the first paragraph of an issue's body, on one line: an
// issue minted for a person opens with why it waits.
func firstParagraph(body string) string {
	first, _, _ := strings.Cut(strings.TrimSpace(body), "\n\n")
	return strings.Join(strings.Fields(first), " ")
}

// openBlockers names the blockers of open fleet issue n that are still open,
// in ascending order. Blockers are GitHub's native "blocked by" links and
// nothing else.
//
// survey asks for the links of every open fleet issue, one request each, and
// the list's issue_dependencies_summary is not read: right after a link is
// written that summary can still count 0, and trusting it would make a
// blocked issue ready. The fleet is small, so one request per issue is cheap,
// and it is the only answer that cannot lag a link.
func (t tree) openBlockers(n int) []int {
	var blocking []int
	for _, b := range t.deps[n] {
		if b.State == "open" {
			blocking = append(blocking, b.Number)
		}
	}
	sort.Ints(blocking)
	return blocking
}

// Next is the issue at the top, one that is no sub-issue, that a take would
// have: stuck work first, a leaf to take over or a parent with one inside,
// then the lowest-numbered ready one; ok is false when there is none. A
// parent there is ready while a leaf inside it is ready or a parent in its
// tree, itself included, is ready for review, so that a box takes the tree
// and starts the reviewer. Next asks no PR whether it conflicts; only Take
// does.
func (s Source) Next() (next Issue, ok bool, err error) {
	all, err := s.Survey()
	if err != nil {
		return Issue{}, false, err
	}
	if order := takeOrder(all, 0); len(order) > 0 {
		return order[0].Issue, true, nil
	}
	return Issue{}, false, nil
}

// takeOrder lists the issues at the top a take may have, in the order it
// tries them: want first, when it is above zero, then the urgent ones, then
// the rest, each lowest number first.
func takeOrder(all []Status, want int) []Status {
	var order []Status
	for _, st := range all {
		if st.Number == want {
			order = append(order, st)
		}
	}
	for _, urgent := range []bool{true, false} {
		for _, st := range all {
			if st.Above == 0 && st.Takeable() && st.urgent == urgent && st.Number != want {
				order = append(order, st)
			}
		}
	}
	return order
}

// Take claims an issue at the top in the git checkout dir: want, when it is
// above zero, else the one Next names. Without want, a claimed leaf whose PR
// conflicts with main comes first, whatever its age (see takeOverConflict).
// Where another box claimed a leaf first, it moves on to the next one. A leaf
// stuck for the first time is taken over: its branch is checked out as it
// stands. A parent's branch claims its whole
// tree; where it exists already, Take picks the tree up from that claim. A
// claimed leaf named as want, at any depth, is taken over where se fleet
// check finds it stuck (see takeOverClaim), or where it is stuck past the
// lease. ok is false when nothing was left to take.
func (s Source) Take(dir string, want int) (took Issue, ok bool, err error) {
	all, t, err := s.survey()
	if err != nil {
		return Issue{}, false, err
	}
	if s.Worktrees {
		if err := s.room(all, t.pulls); err != nil {
			return Issue{}, false, err
		}
	}
	if want == 0 {
		if took, ok, err := s.takeOverConflict(dir, all, t.pulls); err != nil || ok {
			return took, ok, err
		}
	}
	if want > 0 {
		found := false
		for _, st := range all {
			if st.Number != want {
				continue
			}
			found = true
			if st.claimed && st.Takeover == nil {
				return s.takeOverClaim(dir, st, t)
			}
			// A stuck leaf is taken over at any depth, as se fleet check's
			// remedy names it; other work inside a tree is taken with --in.
			if st.Above != 0 && st.Takeover == nil {
				return Issue{}, false, fmt.Errorf("#%d is a sub-issue of #%d; it is taken with --in", want, st.Above)
			}
			if !st.Takeable() {
				return Issue{}, false, fmt.Errorf("#%d is not ready: %s", want, st.Why)
			}
		}
		if !found {
			return Issue{}, false, fmt.Errorf("#%d is not an open issue labelled %s", want, Label)
		}
	}
	for _, st := range takeOrder(all, want) {
		var claimed bool
		switch {
		case st.Takeover != nil:
			claimed, err = s.takeOverStuck(dir, st, !s.Worktrees)
		case st.Parent:
			claimed, err = s.claimTree(dir, st.Number)
		default:
			claimed, err = s.Claim(dir, st.Number)
		}
		if err != nil {
			return Issue{}, false, err
		}
		if claimed {
			return st.Issue, true, nil
		}
	}
	return Issue{}, false, nil
}

// Tree is where the work inside one issue's tree stands.
type Tree struct {
	Root int `json:"root"`
	// Closed is true once the root has closed: the tree is done.
	Closed bool `json:"closed"`
	// Ready is the leaves that may be taken: those to take over first, then
	// the new work, each lowest number first.
	Ready []Issue `json:"ready"`
	// Review is the se-review parents whose sub-issues are all closed.
	Review []Issue `json:"review"`
	// Why says what holds the whole tree: an issue in it waits on a person.
	Why string `json:"why,omitempty"`
	// rounds counts each review parent's sub-issues, which names its reviewer's worktree.
	rounds map[int]int
}

// ReviewWorktree is the command that makes the fresh worktree, beside the
// checkout dir, that the reviewer of n works in.
func (tr Tree) ReviewWorktree(dir string, n int) string {
	return ReviewWorktree(dir, n, tr.rounds[n])
}

// In says what is ready inside root's tree: its ready leaves at any depth,
// and apart from them its parents ready for review.
func (s Source) In(root int) (Tree, error) {
	tr, _, _, err := s.in(root)
	return tr, err
}

// in is In with the statuses inside root's tree, and all statuses with what
// they were read with.
func (s Source) in(root int) (Tree, []Status, surveyed, error) {
	all, t, err := s.survey()
	if err != nil {
		return Tree{}, nil, surveyed{}, err
	}
	tr := Tree{Root: root, Ready: []Issue{}, Review: []Issue{}, rounds: map[int]int{}}
	if t.closed[root] {
		tr.Closed = true
		return tr, nil, surveyed{all, t}, nil
	}
	if _, ok := t.byNum[root]; !ok {
		got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, root), false)
		if err != nil {
			return Tree{}, nil, surveyed{}, err
		}
		if got[0].PullRequest == nil && got[0].State == "closed" {
			tr.Closed = true
			return tr, nil, surveyed{all, t}, nil
		}
		return Tree{}, nil, surveyed{}, fmt.Errorf("#%d is not an issue labelled %s", root, Label)
	}
	var inside []Status
	top := root
	for t.above[top] != 0 {
		top = t.above[top]
	}
	for _, st := range all {
		m := st.Number
		for m != root && t.above[m] != 0 {
			m = t.above[m]
		}
		if st.Number == top && st.waits != 0 {
			tr.Why = fmt.Sprintf("#%d waits on a person", st.waits)
		}
		if m != root {
			continue
		}
		inside = append(inside, st)
	}
	if tr.Why != "" {
		return tr, nil, surveyed{all, t}, nil
	}
	var fresh []Issue
	for _, st := range inside {
		switch {
		case st.Review:
			tr.Review = append(tr.Review, st.Issue)
			tr.rounds[st.Number] = len(t.subs[st.Number])
		case st.Takeover != nil:
			tr.Ready = append(tr.Ready, st.Issue)
		case st.Ready() && !st.Parent:
			fresh = append(fresh, st.Issue)
		}
	}
	tr.Ready = append(tr.Ready, fresh...)
	return tr, inside, surveyed{all, t}, nil
}

// TakeIn claims a leaf inside root's tree: want, when it is above zero, else
// the first of tr.Ready, moving on where another box claimed it first. It
// pushes the leaf's branch from origin/main and fetches it, checking nothing
// out, so several leaves can be in flight at once, each in its own worktree.
// A leaf stuck for the first time is taken over: its branch is fetched as it
// stands.
// ok is false when nothing was left to take; tr says where the tree stands.
func (s Source) TakeIn(dir string, root, want int) (took Issue, ok bool, tr Tree, err error) {
	tr, inside, read, err := s.in(root)
	if err != nil || tr.Closed {
		return Issue{}, false, tr, err
	}
	if err := s.room(read.all, read.t.pulls); err != nil {
		return Issue{}, false, tr, err
	}
	if tr.Why != "" && want > 0 {
		return Issue{}, false, tr, fmt.Errorf("#%d is not ready: %s", want, tr.Why)
	}
	var order []Issue
	if want > 0 {
		found := false
		for _, st := range inside {
			if st.Number != want {
				continue
			}
			found = true
			if st.Parent {
				return Issue{}, false, tr, fmt.Errorf("#%d is a parent: a parent holds no work", want)
			}
			if !st.Takeable() {
				return Issue{}, false, tr, fmt.Errorf("#%d is not ready: %s", want, st.Why)
			}
			order = append(order, st.Issue)
		}
		if !found {
			return Issue{}, false, tr, fmt.Errorf("#%d is not an open issue inside #%d", want, root)
		}
	}
	for _, i := range tr.Ready {
		if i.Number != want {
			order = append(order, i)
		}
	}
	byNum := map[int]Status{}
	for _, st := range inside {
		byNum[st.Number] = st
	}
	for _, i := range order {
		var claimed bool
		if i.Takeover != nil {
			claimed, err = s.takeOverStuck(dir, byNum[i.Number], false)
		} else {
			claimed, err = s.stake(dir, i.Number)
		}
		if err != nil {
			return Issue{}, false, tr, err
		}
		if claimed {
			return i, true, tr, nil
		}
	}
	return Issue{}, false, tr, nil
}

// Worktree is the command that checks a leaf's claimed branch out in its own
// worktree, beside the checkout dir.
func Worktree(dir string, n int) string {
	b := Branch(n)
	return fmt.Sprintf("git worktree add --track -b %s %s origin/%s", b, filepath.Join(filepath.Dir(dir), b), b)
}

// claimTree claims a parent's tree with its branch, as Claim does; where the
// branch exists already, the tree is picked up from that claim and the
// branch checked out.
func (s Source) claimTree(dir string, n int) (bool, error) {
	if claimed, err := s.Claim(dir, n); err != nil || claimed {
		return claimed, err
	}
	return true, s.pickUp(dir, n)
}

// pickUp checks out issue n's branch as it stands on origin; with Worktrees
// it only fetches it.
func (s Source) pickUp(dir string, n int) error {
	branch := Branch(n)
	if _, err := s.git(dir, "fetch", "-q", "origin", "+refs/heads/"+branch+":refs/remotes/origin/"+branch); err != nil || s.Worktrees {
		return err
	}
	if _, err := s.git(dir, "checkout", "-q", "-B", branch, "--track", "origin/"+branch); err != nil {
		return fmt.Errorf("could not check out %s: %w", branch, err)
	}
	return nil
}

// Claim pushes the current origin/main as issue n's branch and checks it out,
// or with Worktrees only fetches it.
// The push only creates the branch, never moves it, so of two boxes racing for
// one issue the second is refused: claimed is then false and nothing changed.
func (s Source) Claim(dir string, n int) (claimed bool, err error) {
	if claimed, err := s.stake(dir, n); err != nil || !claimed || s.Worktrees {
		return claimed, err
	}
	branch := Branch(n)
	if _, err := s.git(dir, "checkout", "-q", "-b", branch, "--track", "origin/"+branch); err != nil {
		return true, fmt.Errorf("claimed %s, but could not check it out: %w", branch, err)
	}
	return true, nil
}

// stake is Claim without the checkout: it pushes the branch and fetches it as
// origin/issue-<n>, and records the claim's box on the issue.
func (s Source) stake(dir string, n int) (claimed bool, err error) {
	branch := Branch(n)
	ref := "refs/heads/" + branch
	if _, err := s.git(dir, "fetch", "-q", "origin", "main"); err != nil {
		return false, err
	}
	// An empty lease: the ref must not exist on origin yet. Where it already
	// points at this very commit the push is no update at all and succeeds,
	// so the claim is the push's own word that it created the ref ("*").
	said, pushErr := s.git(dir, "push", "--porcelain", "--force-with-lease="+ref+":", "origin", "refs/remotes/origin/main:"+ref)
	if pushErr != nil {
		if _, err := s.git(dir, "ls-remote", "--exit-code", "origin", ref); err == nil {
			return false, nil
		}
		return false, pushErr
	}
	if !strings.Contains("\n"+said, "\n*\t") {
		return false, nil
	}
	if _, err := s.git(dir, "fetch", "-q", "origin", ref+":refs/remotes/origin/"+branch); err != nil {
		return true, err
	}
	return true, s.markBox(n)
}

// Repo reads OWNER/NAME from the checkout's origin URL, whatever its form:
// https://github.com/o/n.git, git@github.com:o/n, or a proxy's …/o/n. It
// runs git on p.
func Repo(p proc.Procs, dir string) (string, error) {
	url, err := Source{Proc: p}.git(dir, "remote", "get-url", "origin")
	if err != nil {
		return "", err
	}
	url = strings.TrimSuffix(strings.TrimSuffix(url, "/"), ".git")
	parts := strings.FieldsFunc(url, func(r rune) bool { return r == '/' || r == ':' })
	if len(parts) < 2 {
		return "", fmt.Errorf("origin %q names no OWNER/NAME; pass --repo", url)
	}
	return parts[len(parts)-2] + "/" + parts[len(parts)-1], nil
}

// git runs git in the checkout dir and answers what it printed, trimmed.
func (s Source) git(dir string, args ...string) (string, error) {
	return proc.Output(s.Proc, proc.Cmd{Name: "git", Args: args, Dir: dir})
}
