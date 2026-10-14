package issues

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/mb-89/SE/src/internal/battery"

	"github.com/mb-89/SE/src/internal/io/github"
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
	// Manifest and Into are, for a leaf, the manifest it landed into and
	// that manifest's branch: a leaf gets no PR, so Number is 0.
	Manifest int    `json:"manifest,omitempty"`
	Into     string `json:"into,omitempty"`
	// Closed is true where the land closed the issue itself: a leaf landed
	// into its manifest, or a manifest with nothing left to land.
	Closed bool `json:"closed,omitempty"`
	// Warning is what went wrong without stopping the land: the battery's
	// status refused on the pushed commit, which CI then checks itself.
	Warning string `json:"warning,omitempty"`
}

// pull is the part of GitHub's pull request object land reads.
type pull struct {
	Number int    `json:"number"`
	NodeID string `json:"node_id"`
	URL    string `json:"html_url"`
}

// autoMerge turns on GitHub's auto-merge, squashing, for the PR with this node id.
const autoMerge = `mutation($id: ID!) { enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: SQUASH}) { clientMutationId } }`

// issued reads n from the issue branch checked out in dir.
func (s Source) issued(dir string) (int, error) {
	branch, err := s.git(dir, "rev-parse", "--abbrev-ref", "HEAD")
	if err != nil {
		return 0, err
	}
	n, err := strconv.Atoi(strings.TrimPrefix(branch, "issue-"))
	if !strings.HasPrefix(branch, "issue-") || err != nil || n <= 0 || Branch(n) != branch {
		return 0, fmt.Errorf("land runs on an issue-<n> branch, and %s is on %s", dir, branch)
	}
	return n, nil
}

// Land brings the issue branch checked out in dir to where it lands. A leaf
// inside a manifest (an issue with a parent) lands into the manifest's branch
// and closes, with no PR of its own (landInto). An issue at the top, a
// manifest whose leaves are all closed or a retro, lands to main: answers must
// answer every question in qs, and check must pass on a clean tree of an
// issue with no open sub-issues, after origin's branch and main are merged
// in, so the check runs on what lands; the battery must have recorded that
// tree, and main must not have moved past it since (ship). Then the answers
// are posted on the issue, before anything is pushed, so a land stopped later
// still leaves them; the branch is pushed with the battery's status on its
// head, its PR against main opened (or, where it is open
// already, found) with the battery's profile in its body, and auto-merge
// turned on with squash. Run again after a
// fix, it pushes, updates the answers and reports the same PR. Where session
// is set, the leaf records who worked it, so a review of its tree can refuse
// that worker.
func (s Source) Land(dir, session string, qs []Question, answers map[string]string, check func(dir string) error) (Landing, error) {
	n, err := s.issued(dir)
	if err != nil {
		return Landing{}, err
	}
	if err := answered(qs, answers); err != nil {
		return Landing{}, err
	}
	if dirty, err := s.git(dir, "status", "--porcelain"); err != nil {
		return Landing{}, err
	} else if dirty != "" {
		return Landing{}, fmt.Errorf("land pushes commits, and %s has changes not committed:\n%s", dir, dirty)
	}
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		return Landing{}, err
	}
	subs := got[0].SubIssues
	if subs != nil && subs.Total > subs.Completed {
		return Landing{}, fmt.Errorf("#%d has open sub-issues, and a parent holds no work: its sub-issues land, and it lands once they are closed", n)
	}
	root, err := s.manifestOf(n)
	if err != nil {
		return Landing{}, err
	}
	if root != 0 {
		return s.landInto(dir, n, root, session, qs, answers, check)
	}
	branch := Branch(n)
	if err := s.takeIn(dir, branch); err != nil {
		return Landing{}, err
	}
	if subs != nil && subs.Total > 0 {
		// A manifest whose leaves landed nothing has nothing to land.
		if ahead, err := s.git(dir, "rev-list", "--count", "origin/main..HEAD"); err != nil {
			return Landing{}, err
		} else if ahead == "0" {
			return s.closeEmpty(n)
		}
	}
	// The answers go on the issue before the push, so a land stopped after
	// it (a refused status post, a PR it could not open) leaves its record.
	warning, err := refused(s.ship(dir, branch, check, func() error {
		if err := s.record(n, Worker{Session: session, Workspace: dir}); err != nil {
			return err
		}
		return s.postLanding(dir, n, qs, answers)
	}))
	if err != nil {
		return Landing{}, err
	}
	body := fmt.Sprintf("Fixes #%d", n)
	profile, profiled, err := battery.Load(s.Disk, dir)
	if err != nil {
		return Landing{}, err
	}
	if profiled {
		body += "\n\n" + profile.Markdown()
	}
	l := Landing{Issue: n, Warning: warning}
	pr, open, err := s.openPR(n)
	if err != nil {
		return Landing{}, err
	}
	if open {
		// The body shows the profile of the battery this land ran.
		if profiled {
			if _, err := s.GitHub.Send("PATCH", fmt.Sprintf("repos/%s/pulls/%d", s.Repo, pr.Number), github.F("body", body)); err != nil {
				return Landing{}, err
			}
		}
	} else {
		path := fmt.Sprintf("repos/%s/pulls", s.Repo)
		out, err := s.GitHub.Send("POST", path, github.F("title", got[0].Title), github.F("head", branch), github.F("base", "main"), github.F("body", body))
		if err != nil {
			return Landing{}, err
		}
		if err := json.Unmarshal(out, &pr); err != nil || pr.Number == 0 {
			return Landing{}, fmt.Errorf("gh api %s answered no pull request: %v", path, err)
		}
		l.Created = true
	}
	l.Number, l.URL = pr.Number, pr.URL
	l.Merged, err = s.autoMerge(pr)
	return l, err
}

// closeEmpty closes manifest n, whose leaves are all closed and landed
// nothing on its branch: there is no PR to open.
func (s Source) closeEmpty(n int) (Landing, error) {
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", fmt.Sprintf("Every leaf of #%d is closed and its branch holds nothing main does not, so it closes with no PR.", n))); err != nil {
		return Landing{}, err
	}
	if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", "completed")); err != nil {
		return Landing{}, err
	}
	return Landing{Issue: n, Closed: true}, nil
}

// takeIn merges into the branch checked out in dir what origin's copy of it
// has (a takeover's box, or this box's se issue keep, pushed there) and then origin's main, so
// the check runs on what lands and the push is a fast-forward. A merge that
// conflicts is undone, and the box resolves it by hand.
func (s Source) takeIn(dir, branch string) error {
	if _, err := s.git(dir, "fetch", "-q", "origin", "main"); err != nil {
		return err
	}
	refs := []string{"origin/main"}
	// A branch not on origin yet has nothing to take in.
	if _, err := s.git(dir, "fetch", "-q", "origin", "refs/heads/"+branch+":refs/remotes/origin/"+branch); err == nil {
		refs = []string{"origin/" + branch, "origin/main"}
	}
	for _, ref := range refs {
		if _, err := s.git(dir, "merge", "-q", "--no-edit", ref); err != nil {
			_, _ = s.git(dir, "merge", "--abort")
			return fmt.Errorf("merging %s into %s conflicts, so nothing was pushed: merge it by hand (never rebase), resolve the conflict, commit and land again: %w", ref, branch, err)
		}
	}
	return nil
}

// autoMerge turns on auto-merge, squashing, for the PR; merged is true where
// nothing was left to wait for and it was merged at once instead.
func (s Source) autoMerge(pr pull) (merged bool, err error) {
	_, err = s.GitHub.GraphQL(autoMerge, github.F("id", pr.NodeID))
	if err != nil && strings.Contains(err.Error(), "GraphQL is not available") {
		// A Claude Code cloud session reaches GitHub through a proxy that
		// refuses GraphQL and offers auto-merge as a REST route instead.
		_, err = s.GitHub.Send("PUT", fmt.Sprintf("repos/%s/pulls/%d/ccr/auto_merge", s.Repo, pr.Number), github.F("merge_method", "squash"))
	}
	if err != nil {
		// A PR with nothing left to wait for takes no auto-merge; it is
		// merged now, the way auto-merge would have.
		if !strings.Contains(err.Error(), "clean status") {
			return false, fmt.Errorf("PR #%d (%s) is open, but auto-merge is not on: %w", pr.Number, pr.URL, err)
		}
		path := fmt.Sprintf("repos/%s/pulls/%d/merge", s.Repo, pr.Number)
		if _, err := s.GitHub.Send("PUT", path, github.F("merge_method", "squash")); err != nil {
			return false, fmt.Errorf("PR #%d (%s) is open, but merging it failed: %w", pr.Number, pr.URL, err)
		}
		return true, nil
	}
	return false, nil
}
