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
	"sort"
	"strconv"
	"strings"
	"time"
)

// Label marks an issue as the fleet's work.
const Label = "se"

// Issue is one fleet issue.
type Issue struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	Body   string `json:"body"`
	URL    string `json:"url"`
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
	// Now is the clock the lease is read against; nil is the wall clock.
	Now func() time.Time
}

func (s Source) now() time.Time {
	if s.Now == nil {
		return time.Now()
	}
	return s.Now()
}

// issue is the part of GitHub's issue object the rules read.
type issue struct {
	Number      int              `json:"number"`
	Title       string           `json:"title"`
	Body        string           `json:"body"`
	State       string           `json:"state"`
	URL         string           `json:"html_url"`
	PullRequest *json.RawMessage `json:"pull_request"`
	Labels      []struct {
		Name string `json:"name"`
	} `json:"labels"`
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
	// issue-7", "blocked by #3, #4", "waits on a person".
	Why string `json:"why,omitempty"`
	// Stuck is set for a claimed issue nothing was pushed to for longer than
	// the lease; Takeovers counts its takeovers since a person last resumed it.
	Stuck     bool `json:"stuck,omitempty"`
	Takeovers int  `json:"takeovers,omitempty"`
	// Person is set for an issue labelled se-person; Reason says why.
	Person bool   `json:"person,omitempty"`
	Reason string `json:"reason,omitempty"`
	// Since is when its branch last saw a push or a takeover.
	Since time.Time `json:"-"`
	// blockers are its open blockers, ascending; read for unclaimed issues.
	blockers []int
}

// Ready says whether the issue may be taken as new work.
func (s Status) Ready() bool { return s.Why == "" }

// Takeable says whether a take may have it: ready, or stuck for the first time.
func (s Status) Takeable() bool {
	return s.Ready() || (s.Stuck && s.Takeovers == 0 && !s.Person)
}

// Survey reads every open fleet issue and says where each stands, lowest
// number first. It only reads; Sweep acts on what it finds.
func (s Source) Survey() ([]Status, error) {
	open, err := api[issue](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=open&per_page=100", s.Repo, Label), true)
	if err != nil {
		return nil, err
	}
	refs, err := api[struct {
		Ref string `json:"ref"`
	}](s, fmt.Sprintf("repos/%s/git/matching-refs/heads/issue-", s.Repo), true)
	if err != nil {
		return nil, err
	}
	claimed := map[string]bool{}
	for _, r := range refs {
		claimed[strings.TrimPrefix(r.Ref, "refs/heads/")] = true
	}
	var fleet []issue
	for _, i := range open {
		if i.PullRequest == nil {
			fleet = append(fleet, i)
		}
	}
	sort.Slice(fleet, func(a, b int) bool { return fleet[a].Number < fleet[b].Number })
	now := s.now()
	var out []Status
	for _, i := range fleet {
		st := Status{Issue: Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL}}
		for _, l := range i.Labels {
			st.Person = st.Person || l.Name == PersonLabel
		}
		switch {
		case st.Person:
			st.Why = "waits on a person"
			marks, err := s.marks(i.Number)
			if err != nil {
				return nil, err
			}
			st.Reason = marks.reason
		case claimed[Branch(i.Number)]:
			st.Why = "claimed by " + Branch(i.Number)
			marks, err := s.marks(i.Number)
			if err != nil {
				return nil, err
			}
			pushed, err := s.lastPush(i.Number)
			if err != nil {
				return nil, err
			}
			st.Since, st.Takeovers = pushed, marks.takeovers
			if marks.lastTakeover.After(st.Since) {
				st.Since = marks.lastTakeover
			}
			if now.Sub(st.Since) > Lease {
				st.Stuck = true
				st.Why += ", stuck: nothing pushed since " + st.Since.UTC().Format(time.RFC3339)
			}
		default:
			if st.blockers, err = s.openBlockers(i); err != nil {
				return nil, err
			}
			if len(st.blockers) == 0 {
				break
			}
			names := make([]string, len(st.blockers))
			for k, b := range st.blockers {
				names[k] = "#" + strconv.Itoa(b)
			}
			st.Why = "blocked by " + strings.Join(names, ", ")
		}
		out = append(out, st)
	}
	return out, nil
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

// Next is the issue a take would have: the lowest-numbered stuck one, else
// the lowest-numbered ready one; ok is false when there is none. The sweep runs
// first, so an issue stuck twice goes to a person on the way.
func (s Source) Next() (next Issue, ok bool, flagged []Status, err error) {
	all, flagged, err := s.Sweep()
	if err != nil {
		return Issue{}, false, flagged, err
	}
	if order := takeOrder(all, 0); len(order) > 0 {
		return order[0].Issue, true, flagged, nil
	}
	return Issue{}, false, flagged, nil
}

// takeOrder lists the issues a take may have, in the order it tries them: want
// first, when it is above zero, then the stuck ones, then the ready ones.
func takeOrder(all []Status, want int) []Status {
	var order []Status
	for _, st := range all {
		if st.Number == want {
			order = append(order, st)
		}
	}
	for _, stuck := range []bool{true, false} {
		for _, st := range all {
			if st.Takeable() && st.Stuck == stuck && st.Number != want {
				order = append(order, st)
			}
		}
	}
	return order
}

// Take claims an issue in the git checkout dir: want, when it is above zero,
// else the next one, a stuck issue before new work. A stuck issue is taken
// over: its branch is checked out as it stands. Where another box claimed or
// took it over first, it moves on to the next one. ok is false when nothing was
// left to take; flagged names the issues the sweep gave to a person.
func (s Source) Take(dir string, want int) (took Issue, ok bool, flagged []Status, err error) {
	all, flagged, err := s.Sweep()
	if err != nil {
		return Issue{}, false, flagged, err
	}
	if want > 0 {
		found := false
		for _, st := range all {
			if st.Number != want {
				continue
			}
			found = true
			if !st.Takeable() {
				return Issue{}, false, flagged, fmt.Errorf("#%d is not ready: %s", want, st.Why)
			}
		}
		if !found {
			return Issue{}, false, flagged, fmt.Errorf("#%d is not an open issue labelled %s", want, Label)
		}
	}
	for _, st := range takeOrder(all, want) {
		var claimed bool
		if st.Stuck {
			claimed, err = s.TakeOver(dir, st)
		} else {
			claimed, err = Claim(dir, st.Number)
		}
		if err != nil {
			return Issue{}, false, flagged, err
		}
		if claimed {
			return st.Issue, true, flagged, nil
		}
	}
	return Issue{}, false, flagged, nil
}

// Claim pushes the current origin/main as issue n's branch and checks it out.
// The push only creates the branch, never moves it, so of two boxes racing for
// one issue the second is refused: claimed is then false and nothing changed.
func Claim(dir string, n int) (claimed bool, err error) {
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
	if _, err := git(dir, "checkout", "-q", "-b", branch, "--track", "origin/"+branch); err != nil {
		return true, fmt.Errorf("claimed %s, but could not check it out: %w", branch, err)
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
