package issues

import (
	"fmt"
	"strings"

	"github.com/mb-89/SE/src/internal/io/github"
)

// fixedMark opens the comment se issue close --fixed-by writes, naming the
// commit on main that already did the issue's work.
const fixedMark = "<!-- se:fixed-by %s -->"

// Moot is what FixedBy did: the issue it closed and the commit on main that
// had done its work already.
type Moot struct {
	Issue int `json:"issue"`
	// Commit is the full SHA of the commit, Subject its first line.
	Commit  string `json:"commit"`
	Subject string `json:"subject"`
	// URL is the commit's page on GitHub.
	URL string `json:"url"`
	// Pulls are the issue's open PRs, now closed, each with a comment naming
	// the commit.
	Pulls []int `json:"pulls,omitempty"`
	// Branch is its issue-<n> claim, now deleted; empty where origin held
	// none.
	Branch string `json:"branch,omitempty"`
}

// FixedBy closes issue n, a leaf whose work reached main before its box
// began, in commit sha: the third way a box ends, beside a PR and a
// supersede, where landing would take an empty commit. It refuses unless
// answers answer every question in qs and sha names a commit that origin's
// main holds (fetched in dir), and refuses a pull request, a closed issue and
// a parent. Then it records the worker (where session is set), posts the
// landing answers as se issue land does, closes n's open PR and deletes its
// issue-<n> claim as CloseDuplicate does, comments naming the commit and
// closes n as completed.
func (s Source) FixedBy(dir, session string, n int, sha string, qs []Question, answers map[string]string) (Moot, error) {
	if err := answered(qs, answers); err != nil {
		return Moot{}, err
	}
	sha = strings.TrimSpace(sha)
	if sha == "" || strings.HasPrefix(sha, "-") {
		return Moot{}, fmt.Errorf("--fixed-by takes the SHA of the commit on main that did #%d's work, not %q", n, sha)
	}
	if _, err := s.git(dir, "fetch", "-q", "origin", "main"); err != nil {
		return Moot{}, err
	}
	full, err := s.git(dir, "rev-parse", "--verify", "--quiet", sha+"^{commit}")
	if err != nil || full == "" {
		return Moot{}, fmt.Errorf("%s names no commit in %s", sha, dir)
	}
	if _, err := s.git(dir, "merge-base", "--is-ancestor", full, "origin/main"); err != nil {
		return Moot{}, fmt.Errorf("commit %s is not on origin/main: only work that reached main closes #%d; land the rest with se issue land", full, n)
	}
	subject, err := s.git(dir, "log", "-1", "--format=%s", full)
	if err != nil {
		return Moot{}, err
	}
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		if st := github.Status(err); st == 404 || st == 410 {
			return Moot{}, fmt.Errorf("#%d does not exist in %s", n, s.Repo)
		}
		return Moot{}, err
	}
	switch it := got[0]; {
	case it.PullRequest != nil:
		return Moot{}, fmt.Errorf("#%d is a pull request, not an issue", n)
	case it.State != "open":
		return Moot{}, fmt.Errorf("#%d is closed already", n)
	case it.SubIssues != nil && it.SubIssues.Total > it.SubIssues.Completed:
		return Moot{}, fmt.Errorf("#%d has open sub-issues, and a parent holds no work: its sub-issues land, and it closes by itself", n)
	}
	f := Moot{Issue: n, Commit: full, Subject: subject, URL: fmt.Sprintf("https://github.com/%s/commit/%s", s.Repo, full)}
	if err := s.record(n, Worker{Session: session, Workspace: dir}); err != nil {
		return f, err
	}
	if err := s.postLanding(dir, n, qs, answers); err != nil {
		return f, err
	}
	short := full[:min(len(full), 12)]
	why := fmt.Sprintf("#%d's work is on main already, in %s.\n%s", n, short, f.URL)
	if f.Pulls, f.Branch, err = s.dropClaim(dir, n, why); err != nil {
		return f, err
	}
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	comment := fmt.Sprintf(fixedMark+"\nClosed: its work is on main already, in %s (%s), so no PR lands it.\n%s", full, short, subject, f.URL)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", comment)); err != nil {
		return f, fmt.Errorf("commenting on #%d: %w", n, err)
	}
	if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", "completed")); err != nil {
		return f, fmt.Errorf("commented on #%d, but closing it: %w", n, err)
	}
	return f, nil
}
