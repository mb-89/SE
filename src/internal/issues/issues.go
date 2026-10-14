// Package issues picks the fleet's next GitHub issue and claims it. The rules
// it follows live in spec/issues.md; this is their one implementation.
package issues

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
)

// Label marks an issue as the fleet's work.
const Label = "se"

// ReviewLabel marks a parent that is reviewed once its sub-issues are closed,
// so it never closes by itself.
const ReviewLabel = "se-review"

// FinalLabel marks an issue on its last attempt: one a review filed for a
// finding, or one taken over once already. A final issue that fails again goes
// to a person instead of another round.
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
	// Retro is true for an issue labelled se-retro: the retro skill does it.
	Retro bool `json:"retro,omitempty"`
	// Overhaul is true for an issue labelled se-overhaul: the overhaul skill
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

// GH runs gh with these arguments and answers what it printed.
type GH func(args ...string) ([]byte, error)

// Gh is the gh CLI on this machine; it owns the authentication.
func Gh(args ...string) ([]byte, error) {
	cmd := exec.Command("gh", args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if errors.Is(err, exec.ErrNotFound) {
		return nil, errors.New("gh is missing; RUNME.sh names how to install it")
	}
	if err != nil {
		return nil, fmt.Errorf("gh %s: %v: %s", strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return out, nil
}

// Source reads one repository's issues through gh.
type Source struct {
	// Repo is OWNER/NAME.
	Repo string
	GH   GH
	// Clock is the time leases, windows and stamps are read against.
	Clock clock.Clock
	// Flagged hears of each issue the sweep gave to a person, and why.
	Flagged func(i Issue, reason string)
}

func (s Source) now() time.Time { return s.Clock.Now() }

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
	URL      string    `json:"html_url"`
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

// api reads a gh api path, every page of it, into out. A paginated list comes
// back as one JSON array per page; their items are joined.
func api[T any](s Source, path string, list bool) ([]T, error) {
	args := []string{"api", path}
	if list {
		args = []string{"api", "--paginate", path}
	}
	out, err := s.GH(args...)
	if err != nil {
		return nil, err
	}
	var all []T
	dec := json.NewDecoder(bytes.NewReader(out))
	for {
		if !list {
			var one T
			if err := dec.Decode(&one); err != nil {
				return nil, fmt.Errorf("gh api %s: %v", path, err)
			}
			return []T{one}, nil
		}
		var page []T
		if err := dec.Decode(&page); errors.Is(err, io.EOF) {
			return all, nil
		} else if err != nil {
			return nil, fmt.Errorf("gh api %s: %v", path, err)
		}
		all = append(all, page...)
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
	// the lease; Takeovers is its last takeover round since a person last
	// resumed it, which only settles two boxes racing for one round (the
	// label se-final is the record of a takeover), and Since is when its
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
	// claimed is true for a leaf whose branch exists on origin.
	claimed bool
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
func (s Source) load() (tree, error) {
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
		if i := t.byNum[n]; i.SubIssues == nil || i.SubIssues.Total == 0 {
			continue
		}
		subs, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/sub_issues?per_page=100", s.Repo, n), true)
		if err != nil {
			return tree{}, err
		}
		t.subs[n] = subs
		parents = append(parents, n)
		for _, c := range subs {
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
	if _, err := s.GH("api", "-X", "POST", "-f", fmt.Sprintf("body=All sub-issues of #%d are closed, so it closes by itself.", n), path+"/comments"); err != nil {
		return fmt.Errorf("closing parent #%d: %w", n, err)
	}
	if _, err := s.GH("api", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=completed", path); err != nil {
		return fmt.Errorf("closing parent #%d: %w", n, err)
	}
	return nil
}

// CloseParents closes every open parent whose sub-issues are all closed,
// deepest first, except those labelled se-review. Every se issue command does
// this first.
func (s Source) CloseParents() error {
	_, err := s.load()
	return err
}

// Survey reads every open fleet issue and says where each stands, lowest
// number first.
func (s Source) Survey() ([]Status, error) {
	all, _, err := s.survey()
	return all, err
}

func (s Source) survey() ([]Status, tree, error) {
	t, err := s.load()
	if err != nil {
		return nil, tree{}, err
	}
	refs, err := api[struct {
		Ref string `json:"ref"`
	}](s, fmt.Sprintf("repos/%s/git/matching-refs/heads/issue-", s.Repo), true)
	if err != nil {
		return nil, tree{}, err
	}
	claimed := map[string]bool{}
	for _, r := range refs {
		claimed[strings.TrimPrefix(r.Ref, "refs/heads/")] = true
	}
	blockers := map[int][]int{}
	// held names the open blockers of n, or else of its nearest ancestor that has any.
	held := func(n int) (string, error) {
		for m := n; ; {
			b, ok := blockers[m]
			if !ok {
				if b, err = s.openBlockers(t.byNum[m]); err != nil {
					return "", err
				}
				blockers[m] = b
			}
			if len(b) > 0 {
				names := make([]string, len(b))
				for k, x := range b {
					names[k] = "#" + strconv.Itoa(x)
				}
				if m == n {
					return "blocked by " + strings.Join(names, ", "), nil
				}
				return fmt.Sprintf("#%d is blocked by %s", m, strings.Join(names, ", ")), nil
			}
			p, ok := t.above[m]
			if !ok {
				return "", nil
			}
			m = p
		}
	}
	byNum := map[int]*Status{}
	var out []*Status
	for _, n := range t.numbers() {
		i := t.byNum[n]
		_, parent := t.subs[n]
		st := &Status{Issue: Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL, Parent: parent, Retro: i.labelled(RetroLabel), Overhaul: i.labelled(OverhaulLabel)}, Above: t.above[n], Final: i.labelled(FinalLabel)}
		switch {
		case i.labelled(PersonLabel):
			st.Person, st.Why = true, "waits on a person"
			m, err := s.marks(n)
			if err != nil {
				return nil, tree{}, err
			}
			if st.Reason = m.reason; st.Reason == "" {
				st.Reason = firstParagraph(i.Body)
			}
		case !parent && claimed[Branch(n)]:
			// A claim waiting on its blockers (an issue for a person that
			// holds it) is not stuck; once they close, its old push makes it
			// stuck at once, and the next box takes it over afresh.
			why, err := held(n)
			if err != nil {
				return nil, tree{}, err
			}
			if why != "" {
				st.Why = Branch(n) + " waits: " + why
				break
			}
			st.Why, st.claimed = "claimed by "+Branch(n), true
			if err := s.lease(st); err != nil {
				return nil, tree{}, err
			}
			// The sweep: a final issue stuck goes to a person.
			if st.Stuck && st.Final {
				if err := s.toPerson(st); err != nil {
					return nil, tree{}, err
				}
			} else if st.Stuck {
				st.Takeover = &Takeover{Count: st.Takeovers + 1, Stale: st.since()}
				st.urgent = true
				st.Why += ", stuck: " + st.since()
			}
		default:
			if st.Why, err = held(n); err != nil {
				return nil, tree{}, err
			}
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

// openBlockers names the issue's blockers that are still open, in ascending
// order. Blockers are GitHub's native "blocked by" links and nothing else.
//
// The links are asked for on every unclaimed issue, one request each, and the
// list's issue_dependencies_summary is not read: right after a link is written
// that summary can still count 0, and trusting it would make a blocked issue
// ready. The fleet is small, so one request per issue is cheap, and it is
// the only answer that cannot lag a link.
func (s Source) openBlockers(i issue) ([]int, error) {
	native, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/dependencies/blocked_by?per_page=100", s.Repo, i.Number), true)
	if err != nil {
		return nil, err
	}
	var blocking []int
	for _, b := range native {
		if b.State == "open" {
			blocking = append(blocking, b.Number)
		}
	}
	sort.Ints(blocking)
	return blocking, nil
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
// check finds it stuck (see takeOverClaim). ok is false when nothing was left
// to take.
func (s Source) Take(dir string, want int) (took Issue, ok bool, err error) {
	all, err := s.Survey()
	if err != nil {
		return Issue{}, false, err
	}
	if want == 0 {
		if took, ok, err := s.takeOverConflict(dir, all); err != nil || ok {
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
				return s.takeOverClaim(dir, st)
			}
			if st.Above != 0 {
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
			claimed, err = s.takeOverStuck(dir, st, true)
		case st.Parent:
			claimed, err = claimTree(dir, st.Number)
		default:
			claimed, err = Claim(dir, st.Number)
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
	tr, _, err := s.in(root)
	return tr, err
}

func (s Source) in(root int) (Tree, []Status, error) {
	all, t, err := s.survey()
	if err != nil {
		return Tree{}, nil, err
	}
	tr := Tree{Root: root, Ready: []Issue{}, Review: []Issue{}, rounds: map[int]int{}}
	if t.closed[root] {
		tr.Closed = true
		return tr, nil, nil
	}
	if _, ok := t.byNum[root]; !ok {
		got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, root), false)
		if err != nil {
			return Tree{}, nil, err
		}
		if got[0].PullRequest == nil && got[0].State == "closed" {
			tr.Closed = true
			return tr, nil, nil
		}
		return Tree{}, nil, fmt.Errorf("#%d is not an issue labelled %s", root, Label)
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
		return tr, nil, nil
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
	return tr, inside, nil
}

// TakeIn claims a leaf inside root's tree: want, when it is above zero, else
// the first of tr.Ready, moving on where another box claimed it first. It
// pushes the leaf's branch from origin/main and fetches it, checking nothing
// out, so several leaves can be in flight at once, each in its own worktree.
// A leaf stuck for the first time is taken over: its branch is fetched as it
// stands.
// ok is false when nothing was left to take; tr says where the tree stands.
func (s Source) TakeIn(dir string, root, want int) (took Issue, ok bool, tr Tree, err error) {
	tr, inside, err := s.in(root)
	if err != nil || tr.Closed {
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
			claimed, err = stake(dir, i.Number)
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
func claimTree(dir string, n int) (bool, error) {
	if claimed, err := Claim(dir, n); err != nil || claimed {
		return claimed, err
	}
	return true, pickUp(dir, n)
}

// pickUp checks out issue n's branch as it stands on origin.
func pickUp(dir string, n int) error {
	branch := Branch(n)
	if _, err := git(dir, "fetch", "-q", "origin", "+refs/heads/"+branch+":refs/remotes/origin/"+branch); err != nil {
		return err
	}
	if _, err := git(dir, "checkout", "-q", "-B", branch, "--track", "origin/"+branch); err != nil {
		return fmt.Errorf("could not check out %s: %w", branch, err)
	}
	return nil
}

// Claim pushes the current origin/main as issue n's branch and checks it out.
// The push only creates the branch, never moves it, so of two boxes racing for
// one issue the second is refused: claimed is then false and nothing changed.
func Claim(dir string, n int) (claimed bool, err error) {
	if claimed, err := stake(dir, n); err != nil || !claimed {
		return claimed, err
	}
	branch := Branch(n)
	if _, err := git(dir, "checkout", "-q", "-b", branch, "--track", "origin/"+branch); err != nil {
		return true, fmt.Errorf("claimed %s, but could not check it out: %w", branch, err)
	}
	return true, nil
}

// stake is Claim without the checkout: it readies the pinned linters the push
// hook needs, pushes the branch and fetches it as
// origin/issue-<n>.
func stake(dir string, n int) (claimed bool, err error) {
	branch := Branch(n)
	ref := "refs/heads/" + branch
	if err := ReadyTools(dir); err != nil {
		return false, err
	}
	if _, err := git(dir, "fetch", "-q", "origin", "main"); err != nil {
		return false, err
	}
	// An empty lease: the ref must not exist on origin yet. Where it already
	// points at this very commit the push is no update at all and succeeds,
	// so the claim is the push's own word that it created the ref ("*").
	said, pushErr := git(dir, "push", "--porcelain", "--force-with-lease="+ref+":", "origin", "refs/remotes/origin/main:"+ref)
	if pushErr != nil {
		if _, err := git(dir, "ls-remote", "--exit-code", "origin", ref); err == nil {
			return false, nil
		}
		return false, pushErr
	}
	if !strings.Contains("\n"+said, "\n*\t") {
		return false, nil
	}
	if _, err := git(dir, "fetch", "-q", "origin", ref+":refs/remotes/origin/"+branch); err != nil {
		return true, err
	}
	return true, nil
}

// Repo reads OWNER/NAME from the checkout's origin URL, whatever its form:
// https://github.com/o/n.git, git@github.com:o/n, or a proxy's …/o/n.
func Repo(dir string) (string, error) {
	url, err := git(dir, "remote", "get-url", "origin")
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

func git(dir string, args ...string) (string, error) {
	cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git %s: %v: %s", strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return strings.TrimSpace(string(out)), nil
}
