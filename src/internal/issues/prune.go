package issues

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Fresh is how long a claude/* branch is left alone after its last commit,
// so a session that has just pushed can still open its PR.
var Fresh = time.Hour

// Stray is one branch se fleet prune removes, and why.
type Stray struct {
	Branch string `json:"branch"`
	SHA    string `json:"sha"`
	Why    string `json:"why"`
	// Deleted is true once --apply has deleted it.
	Deleted bool `json:"deleted"`
}

// Strays lists the branches no work needs any more: every issue-<n> branch
// whose issue is closed, and every claude/* branch whose last commit is older
// than Fresh, each with no open PR. It never names main or any other branch.
func (s Source) Strays() ([]Stray, error) {
	pulls, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls?state=open&per_page=100", s.Repo), true)
	if err != nil {
		return nil, err
	}
	open := map[string]bool{}
	for _, p := range pulls {
		open[p.Head.Ref] = true
	}
	var out []Stray
	refs, err := api[ref](s, fmt.Sprintf("repos/%s/git/matching-refs/heads/issue-", s.Repo), true)
	if err != nil {
		return nil, err
	}
	for _, r := range refs {
		b := strings.TrimPrefix(r.Ref, "refs/heads/")
		n, err := strconv.Atoi(strings.TrimPrefix(b, "issue-"))
		if err != nil || Branch(n) != b || open[b] {
			continue
		}
		got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
		if err != nil {
			return nil, err
		}
		if i := got[0]; i.State == "closed" && i.PullRequest == nil {
			out = append(out, Stray{Branch: b, SHA: r.Object.SHA, Why: fmt.Sprintf("#%d is closed and %s has no open PR", n, b)})
		}
	}
	refs, err = api[ref](s, fmt.Sprintf("repos/%s/git/matching-refs/heads/claude/", s.Repo), true)
	if err != nil {
		return nil, err
	}
	for _, r := range refs {
		b := strings.TrimPrefix(r.Ref, "refs/heads/")
		if !strings.HasPrefix(b, "claude/") || open[b] {
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

// Prune deletes the strays, stopping at the first delete GitHub refuses.
func (s Source) Prune(strays []Stray) ([]Stray, error) {
	for k := range strays {
		if _, err := s.GH("api", "-X", "DELETE", fmt.Sprintf("repos/%s/git/refs/heads/%s", s.Repo, strays[k].Branch)); err != nil {
			return strays, fmt.Errorf("deleting %s: %w", strays[k].Branch, err)
		}
		strays[k].Deleted = true
	}
	return strays, nil
}
