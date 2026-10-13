// Package issues picks the fleet's next GitHub issue and claims it. The rules
// it follows live in docs/issues.md; this is their one implementation.
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
)

// Label marks an issue as the fleet's work.
const Label = "se"

// ReviewLabel marks a parent that is reviewed once its sub-issues are closed,
// so it never closes by itself.
const ReviewLabel = "se-review"

// Issue is one fleet issue.
type Issue struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	Body   string `json:"body"`
	URL    string `json:"url"`
	// Parent is true for an issue with sub-issues: it holds no work of its
	// own, and taking it means coordinating them.
	Parent bool `json:"parent,omitempty"`
	// Takeover is set where the take took over a claimed issue whose PR
	// conflicts with main.
	Takeover *Takeover `json:"takeover,omitempty"`
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
}

// issue is the part of GitHub's issue object the rules read.
type issue struct {
	ID          int64            `json:"id"`
	Number      int              `json:"number"`
	Title       string           `json:"title"`
	Body        string           `json:"body"`
	State       string           `json:"state"`
	URL         string           `json:"html_url"`
	PullRequest *json.RawMessage `json:"pull_request"`
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
	// blocker), "nothing inside is ready" (a parent).
	Why string `json:"why,omitempty"`
	// Above is the open fleet issue this one is a sub-issue of; 0 at the top.
	Above int `json:"above,omitempty"`
	// Review is true for a parent labelled se-review whose sub-issues are all
	// closed: it waits for its review, which is not work, but its coordinator
	// starts the reviewer.
	Review bool `json:"review,omitempty"`
	// claimed is true for a leaf whose branch exists on origin.
	claimed bool
}

// Ready says whether the issue may be taken: a ready leaf is work, a ready
// parent has work or a review inside it, or is ready for review itself.
func (s Status) Ready() bool { return s.Why == "" }

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
		st := &Status{Issue: Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL, Parent: parent}, Above: t.above[n]}
		if i.labelled(PersonLabel) {
			st.Why = "waits for a person (" + PersonLabel + ")"
		} else if !parent && claimed[Branch(n)] {
			st.Why, st.claimed = "claimed by "+Branch(n), true
		} else if st.Why, err = held(n); err != nil {
			return nil, tree{}, err
		}
		if parent && st.Why == "" && t.done(n) {
			st.Review = true
		}
		byNum[n] = st
		out = append(out, st)
	}
	// A parent is ready while a leaf anywhere inside it is, or a parent inside
	// it is ready for review.
	var inside func(n int) bool
	inside = func(n int) bool {
		for _, c := range t.subs[n] {
			if st, ok := byNum[c.Number]; ok && st.Why == "" && (!st.Parent || st.Review || inside(c.Number)) {
				return true
			}
		}
		return false
	}
	all := make([]Status, len(out))
	for k, st := range out {
		if st.Parent && st.Why == "" && !st.Review && !inside(st.Number) {
			st.Why = "nothing inside is ready"
		}
		all[k] = *st
	}
	return all, t, nil
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

// Next is the lowest-numbered ready issue at the top, one that is no
// sub-issue; ok is false when none is ready. A parent there is ready while a
// leaf inside it is ready or a parent in its tree, itself included, is ready
// for review, so that a box takes the tree and starts the reviewer.
func (s Source) Next() (next Issue, ok bool, err error) {
	all, err := s.Survey()
	if err != nil {
		return Issue{}, false, err
	}
	for _, st := range all {
		if st.Above == 0 && st.Ready() {
			return st.Issue, true, nil
		}
	}
	return Issue{}, false, nil
}

// Take claims an issue at the top in the git checkout dir: want, when it is
// above zero, else the next ready one. Without want, a claimed leaf whose PR
// conflicts with main comes first, whatever its age: it is taken over and its
// branch checked out as it stands (see takeOver). Where another box claimed a leaf first,
// it moves on to the next ready issue. A parent's branch claims its whole
// tree; where it exists already, Take picks the tree up from that claim. ok is
// false when nothing was left to take.
func (s Source) Take(dir string, want int) (took Issue, ok bool, err error) {
	all, err := s.Survey()
	if err != nil {
		return Issue{}, false, err
	}
	var order []Issue
	if want == 0 {
		if took, ok, err := s.takeOver(dir, all); err != nil || ok {
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
			if st.Above != 0 {
				return Issue{}, false, fmt.Errorf("#%d is a sub-issue of #%d; it is taken with --in", want, st.Above)
			}
			if !st.Ready() {
				return Issue{}, false, fmt.Errorf("#%d is not ready: %s", want, st.Why)
			}
			order = append(order, st.Issue)
		}
		if !found {
			return Issue{}, false, fmt.Errorf("#%d is not an open issue labelled %s", want, Label)
		}
	}
	for _, st := range all {
		if st.Above == 0 && st.Ready() && st.Number != want {
			order = append(order, st.Issue)
		}
	}
	for _, i := range order {
		claim := Claim
		if i.Parent {
			claim = claimTree
		}
		claimed, err := claim(dir, i.Number)
		if err != nil {
			return Issue{}, false, err
		}
		if claimed {
			return i, true, nil
		}
	}
	return Issue{}, false, nil
}

// Tree is where the work inside one issue's tree stands.
type Tree struct {
	Root int `json:"root"`
	// Closed is true once the root has closed: the tree is done.
	Closed bool `json:"closed"`
	// Ready is the leaves that may be taken, lowest number first.
	Ready []Issue `json:"ready"`
	// Review is the se-review parents whose sub-issues are all closed.
	Review []Issue `json:"review"`
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
	for _, st := range all {
		m := st.Number
		for m != root && t.above[m] != 0 {
			m = t.above[m]
		}
		if m != root {
			continue
		}
		inside = append(inside, st)
		switch {
		case st.Review:
			tr.Review = append(tr.Review, st.Issue)
			tr.rounds[st.Number] = len(t.subs[st.Number])
		case st.Ready() && !st.Parent:
			tr.Ready = append(tr.Ready, st.Issue)
		}
	}
	return tr, inside, nil
}

// TakeIn claims a leaf inside root's tree: want, when it is above zero, else
// the lowest ready one, moving on where another box claimed it first. It
// pushes the leaf's branch from origin/main and fetches it, checking nothing
// out, so several leaves can be in flight at once, each in its own worktree.
// ok is false when nothing was left to take; tr says where the tree stands.
func (s Source) TakeIn(dir string, root, want int) (took Issue, ok bool, tr Tree, err error) {
	tr, inside, err := s.in(root)
	if err != nil || tr.Closed {
		return Issue{}, false, tr, err
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
			if !st.Ready() {
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
	for _, i := range order {
		claimed, err := stake(dir, i.Number)
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
	if _, err := git(dir, "fetch", "-q", "origin", "refs/heads/"+branch+":refs/remotes/origin/"+branch); err != nil {
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

// stake is Claim without the checkout: it pushes the branch and fetches it as
// origin/issue-<n>.
func stake(dir string, n int) (claimed bool, err error) {
	branch := Branch(n)
	ref := "refs/heads/" + branch
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
