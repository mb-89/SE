package issues

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/github"
)

// Fresh is how long a claude/* branch is left alone after its last commit,
// so a session that has just pushed can still open its PR.
var Fresh = time.Hour

// Stray is one branch se fleet prune removes, and why.
type Stray struct {
	Branch string `json:"branch"`
	SHA    string `json:"sha"`
	Why    string `json:"why"`
	// PR is the open PR on the branch, closed before the branch is deleted:
	// it is set only where the branch's issue closed as a duplicate.
	PR int `json:"pr,omitempty"`
	// Deleted is true once --apply has deleted it.
	Deleted bool `json:"deleted"`
}

// Strays lists the branches no work needs any more: every issue-<n> branch
// whose issue is closed, and every claude/* branch whose last commit is older
// than Fresh, each with no open PR. An issue-<n> branch whose issue closed as
// a duplicate is a stray even with an open PR, which is named with it: the
// issue it duplicates carries that work. It never names main or any other
// branch.
func (s Source) Strays() ([]Stray, error) {
	pulls, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls?state=open&per_page=100", s.Repo), true)
	if err != nil {
		return nil, err
	}
	open := map[string]int{}
	for _, p := range pulls {
		open[p.Head.Ref] = p.Number
	}
	var out []Stray
	refs, err := api[ref](s, fmt.Sprintf("repos/%s/git/matching-refs/heads/issue-", s.Repo), true)
	if err != nil {
		return nil, err
	}
	for _, r := range refs {
		b := strings.TrimPrefix(r.Ref, "refs/heads/")
		n, err := strconv.Atoi(strings.TrimPrefix(b, "issue-"))
		if err != nil || Branch(n) != b {
			continue
		}
		got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
		if err != nil {
			return nil, err
		}
		i := got[0]
		if i.State != "closed" || i.PullRequest != nil {
			continue
		}
		switch pr, ok := open[b]; {
		case !ok:
			out = append(out, Stray{Branch: b, SHA: r.Object.SHA, Why: fmt.Sprintf("#%d is closed and %s has no open PR", n, b)})
		case i.StateReason == duplicate:
			out = append(out, Stray{Branch: b, SHA: r.Object.SHA, PR: pr, Why: fmt.Sprintf("#%d is closed as a duplicate, so its PR #%d is closed unmerged", n, pr)})
		}
	}
	refs, err = api[ref](s, fmt.Sprintf("repos/%s/git/matching-refs/heads/claude/", s.Repo), true)
	if err != nil {
		return nil, err
	}
	for _, r := range refs {
		b := strings.TrimPrefix(r.Ref, "refs/heads/")
		if _, ok := open[b]; !strings.HasPrefix(b, "claude/") || ok {
			continue
		}
		got, err := api[struct {
			Commit struct {
				Committer struct {
					Date time.Time `json:"date"`
				} `json:"committer"`
			} `json:"commit"`
		}](s, fmt.Sprintf("repos/%s/commits/%s", s.Repo, r.Object.SHA), false)
		if err != nil {
			return nil, err
		}
		at := got[0].Commit.Committer.Date
		if s.now().Sub(at) > Fresh {
			out = append(out, Stray{
				Branch: b, SHA: r.Object.SHA,
				Why: fmt.Sprintf("its last commit is from %s and it has no open PR", at.UTC().Format(time.RFC3339)),
			})
		}
	}
	sort.SliceStable(out, func(a, b int) bool { return out[a].Branch < out[b].Branch })
	return out, nil
}

// Prune deletes the strays, stopping at the first write GitHub refuses. A
// stray's open PR is closed first, with a comment that says why.
func (s Source) Prune(strays []Stray) ([]Stray, error) {
	for k := range strays {
		if pr := strays[k].PR; pr != 0 {
			body := fmt.Sprintf("Closed unmerged by se fleet prune: %s.", strays[k].Why)
			if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, pr), github.F("body", body)); err != nil {
				return strays, fmt.Errorf("commenting on PR #%d: %w", pr, err)
			}
			if _, err := s.GitHub.Send("PATCH", fmt.Sprintf("repos/%s/pulls/%d", s.Repo, pr), github.F("state", "closed")); err != nil {
				return strays, fmt.Errorf("closing PR #%d: %w", pr, err)
			}
		}
		if _, err := s.GitHub.Send("DELETE", fmt.Sprintf("repos/%s/git/refs/heads/%s", s.Repo, strays[k].Branch)); err != nil {
			return strays, fmt.Errorf("deleting %s: %w", strays[k].Branch, err)
		}
		strays[k].Deleted = true
	}
	return strays, nil
}
