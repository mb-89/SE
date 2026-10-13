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
	"regexp"
	"sort"
	"strconv"
	"strings"
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
}

// issue is the part of GitHub's issue object the rules read.
type issue struct {
	Number      int              `json:"number"`
	Title       string           `json:"title"`
	Body        string           `json:"body"`
	State       string           `json:"state"`
	URL         string           `json:"html_url"`
	PullRequest *json.RawMessage `json:"pull_request"`
	// Dependencies is GitHub's count of native "blocked by" links; absent
	// where the API does not report it.
	Dependencies *struct {
		TotalBlockedBy int `json:"total_blocked_by"`
	} `json:"issue_dependencies_summary"`
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
	// issue-7", "blocked by #3, #4".
	Why string `json:"why,omitempty"`
}

// Ready says whether the issue may be taken.
func (s Status) Ready() bool { return s.Why == "" }

// Survey reads every open fleet issue and says where each stands, lowest
// number first.
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
	// What is known open or closed, so each blocker is asked about once.
	isOpen := map[int]bool{}
	var fleet []issue
	for _, i := range open {
		if i.PullRequest != nil {
			continue
		}
		isOpen[i.Number] = true
		fleet = append(fleet, i)
	}
	sort.Slice(fleet, func(a, b int) bool { return fleet[a].Number < fleet[b].Number })
	var out []Status
	for _, i := range fleet {
		st := Status{Issue: Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL}}
		if claimed[Branch(i.Number)] {
			st.Why = "claimed by " + Branch(i.Number)
			out = append(out, st)
			continue
		}
		blockers, err := s.openBlockers(i, isOpen)
		if err != nil {
			return nil, err
		}
		if len(blockers) > 0 {
			names := make([]string, len(blockers))
			for k, b := range blockers {
				names[k] = "#" + strconv.Itoa(b)
			}
			st.Why = "blocked by " + strings.Join(names, ", ")
		}
		out = append(out, st)
	}
	return out, nil
}

// openBlockers names the issue's blockers that are still open, native links
// and body lines both, in ascending order.
func (s Source) openBlockers(i issue, isOpen map[int]bool) ([]int, error) {
	seen := map[int]bool{}
	var blocking []int
	add := func(n int, open bool) {
		if open && !seen[n] {
			seen[n] = true
			blocking = append(blocking, n)
		}
	}
	if i.Dependencies == nil || i.Dependencies.TotalBlockedBy > 0 {
		native, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/dependencies/blocked_by?per_page=100", s.Repo, i.Number), true)
		if err != nil {
			return nil, err
		}
		for _, b := range native {
			isOpen[b.Number] = b.State == "open"
			add(b.Number, b.State == "open")
		}
	}
	for _, n := range BodyBlockers(i.Body) {
		open, known := isOpen[n]
		if !known {
			got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
			if err != nil {
				return nil, err
			}
			open = got[0].State == "open"
			isOpen[n] = open
		}
		add(n, open)
	}
	sort.Ints(blocking)
	return blocking, nil
}

var (
	blockedLine = regexp.MustCompile(`(?im)^[^\w#\n]*blocked by[*_ \t]*:(.*)$`)
	issueRef    = regexp.MustCompile(`#(\d+)\b`)
)

// BodyBlockers reads the issues a body names on its "Blocked by: #12, #14"
// lines, the form agents write since their tools cannot set native links.
func BodyBlockers(body string) []int {
	var out []int
	for _, line := range blockedLine.FindAllStringSubmatch(body, -1) {
		for _, ref := range issueRef.FindAllStringSubmatch(line[1], -1) {
			if n, err := strconv.Atoi(ref[1]); err == nil {
				out = append(out, n)
			}
		}
	}
	return out
}

// Next is the lowest-numbered ready issue; ok is false when none is ready.
func (s Source) Next() (next Issue, ok bool, err error) {
	all, err := s.Survey()
	if err != nil {
		return Issue{}, false, err
	}
	for _, st := range all {
		if st.Ready() {
			return st.Issue, true, nil
		}
	}
	return Issue{}, false, nil
}

// Take claims an issue in the git checkout dir: want, when it is above zero,
// else the next ready one. Where another box claimed it first, it moves on to
// the next ready issue. ok is false when nothing was left to take.
func (s Source) Take(dir string, want int) (took Issue, ok bool, err error) {
	all, err := s.Survey()
	if err != nil {
		return Issue{}, false, err
	}
	var order []Issue
	if want > 0 {
		found := false
		for _, st := range all {
			if st.Number != want {
				continue
			}
			found = true
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
		if st.Ready() && st.Number != want {
			order = append(order, st.Issue)
		}
	}
	for _, i := range order {
		claimed, err := Claim(dir, i.Number)
		if err != nil {
			return Issue{}, false, err
		}
		if claimed {
			return i, true, nil
		}
	}
	return Issue{}, false, nil
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
