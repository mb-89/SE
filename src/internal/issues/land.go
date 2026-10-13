package issues

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
)

// Landing is where an issue's PR stands once se issue land is done.
type Landing struct {
	Issue int `json:"issue"`
	// Number and URL are the PR's.
	Number int    `json:"number"`
	URL    string `json:"url"`
	// Created is true when this run opened the PR, false when it was open already.
	Created bool `json:"created"`
	// Merged is true when the PR needed no wait and was merged at once.
	Merged bool `json:"merged"`
}

// pull is the part of GitHub's pull request object land reads.
type pull struct {
	Number int    `json:"number"`
	NodeID string `json:"node_id"`
	URL    string `json:"html_url"`
}

// autoMerge turns on GitHub's auto-merge, squashing, for the PR with this node id.
const autoMerge = `mutation($id: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: SQUASH}) { clientMutationId } }`

// Issued reads n from the issue branch checked out in dir.
func Issued(dir string) (int, error) {
	branch, err := git(dir, "rev-parse", "--abbrev-ref", "HEAD")
	if err != nil {
		return 0, err
	}
	n, err := strconv.Atoi(strings.TrimPrefix(branch, "issue-"))
	if !strings.HasPrefix(branch, "issue-") || err != nil || n <= 0 || Branch(n) != branch {
		return 0, fmt.Errorf("land runs on an issue-<n> branch, and %s is on %s", dir, branch)
	}
	return n, nil
}

// Land brings the issue branch checked out in dir to main: answers must
// answer every question in qs, and check must pass on a clean tree of an
// issue with no open sub-issues; then the branch is pushed, the answers
// posted on the issue, its PR against main opened (or, where it is open
// already, found), and auto-merge turned on with squash. Run again after a
// fix, it pushes, updates the answers and reports the same PR. Where session
// is set, the leaf records who worked it, so a review of its tree can refuse
// that worker.
func (s Source) Land(dir, session string, qs []Question, answers map[string]string, check func(dir string) error) (Landing, error) {
	n, err := Issued(dir)
	if err != nil {
		return Landing{}, err
	}
	if err := answered(qs, answers); err != nil {
		return Landing{}, err
	}
	if dirty, err := git(dir, "status", "--porcelain"); err != nil {
		return Landing{}, err
	} else if dirty != "" {
		return Landing{}, fmt.Errorf("land pushes commits, and %s has changes not committed:\n%s", dir, dirty)
	}
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		return Landing{}, err
	}
	if subs := got[0].SubIssues; subs != nil && subs.Total > subs.Completed {
		return Landing{}, fmt.Errorf("#%d has open sub-issues, and a parent holds no work: its sub-issues land, and it closes by itself", n)
	}
	if err := check(dir); err != nil {
		return Landing{}, fmt.Errorf("the check failed, so nothing was pushed: %w", err)
	}
	branch := Branch(n)
	if _, err := git(dir, "push", "-q", "-u", "origin", "HEAD:refs/heads/"+branch); err != nil {
		return Landing{}, err
	}
	if err := s.record(n, Worker{Session: session, Workspace: dir}); err != nil {
		return Landing{}, err
	}
	if err := s.postLanding(dir, n, qs, answers); err != nil {
		return Landing{}, err
	}
	l := Landing{Issue: n}
	owner, _, _ := strings.Cut(s.Repo, "/")
	open, err := api[pull](s, fmt.Sprintf("repos/%s/pulls?head=%s:%s&base=main&state=open&per_page=100", s.Repo, owner, branch), true)
	if err != nil {
		return Landing{}, err
	}
	var pr pull
	if len(open) > 0 {
		pr = open[0]
	} else {
		path := fmt.Sprintf("repos/%s/pulls", s.Repo)
		out, err := s.GH("api", "-X", "POST", "-f", "title="+got[0].Title, "-f", "head="+branch, "-f", "base=main",
			"-f", fmt.Sprintf("body=Fixes #%d", n), path)
		if err != nil {
			return Landing{}, err
		}
		if err := json.Unmarshal(out, &pr); err != nil || pr.Number == 0 {
			return Landing{}, fmt.Errorf("gh api %s answered no pull request: %v", path, err)
		}
		l.Created = true
	}
	l.Number, l.URL = pr.Number, pr.URL
	_, err = s.GH("api", "-f", "query="+autoMerge, "-f", "id="+pr.NodeID, "graphql")
	if err != nil && strings.Contains(err.Error(), "GraphQL is not available") {
		// A Claude Code cloud session reaches GitHub through a proxy that
		// refuses GraphQL and offers auto-merge as a REST route instead.
		_, err = s.GH("api", "-X", "PUT", "-f", "merge_method=squash", fmt.Sprintf("repos/%s/pulls/%d/ccr/auto_merge", s.Repo, pr.Number))
	}
	if err != nil {
		// A PR with nothing left to wait for takes no auto-merge; it is
		// merged now, the way auto-merge would have.
		if !strings.Contains(err.Error(), "clean status") {
			return l, fmt.Errorf("PR #%d (%s) is open, but auto-merge is not on: %w", pr.Number, pr.URL, err)
		}
		path := fmt.Sprintf("repos/%s/pulls/%d/merge", s.Repo, pr.Number)
		if _, err := s.GH("api", "-X", "PUT", "-f", "merge_method=squash", path); err != nil {
			return l, fmt.Errorf("PR #%d (%s) is open, but merging it failed: %w", pr.Number, pr.URL, err)
		}
		l.Merged = true
	}
	return l, nil
}
