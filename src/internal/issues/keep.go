package issues

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// The owner's rule, 2026-10-14: a box stays with its PR until it merges, it
// pushes only what is up to date with main and checked, and CI trusts the
// battery the box already ran. se issue land and se issue keep push through
// ship, which posts BatteryContext on the commit it pushed; CI's check job
// asks Trusted for it (se fleet trust) and runs the battery only where it is
// missing.

// BatteryContext is the commit status a box posts on the commit it pushed,
// naming the tree the battery passed there.
const BatteryContext = "se/battery"

// BatteryDescription is the status's description for tree: CI trusts the
// status only for the tree it names.
func BatteryDescription(tree string) string { return "the battery passed tree " + tree }

// trustAsks is how often Trusted asks for the status before it takes none as
// none: CI can start on a push before the box has posted it.
const trustAsks = 3

// trustPause is the wait between those asks.
const trustPause = 5 * time.Second

// keepPause is how long se issue keep waits between its looks at the PR.
const keepPause = time.Minute

// behindMain is a branch main moved past while the battery ran on it.
type behindMain struct{ branch string }

func (e behindMain) Error() string {
	return fmt.Sprintf("main moved past %s while the battery ran, so nothing was pushed: land again, which merges it in", e.branch)
}

// ship brings the branch checked out in dir to origin, checked, as se issue
// land and se issue keep do: it merges origin's copy of the branch and then
// origin/main in, runs check, refuses a tree the battery did not pass and a
// branch main has moved past since, pushes, and posts BatteryContext on the
// pushed commit, naming its tree.
func (s Source) ship(dir, branch string, check func(dir string) error) error {
	if err := s.takeIn(dir, branch); err != nil {
		return err
	}
	return s.push(dir, branch, check)
}

// push is ship after takeIn: it runs check, refuses a tree the battery did
// not pass and a branch main has moved past since, pushes, and posts
// BatteryContext on the pushed commit.
func (s Source) push(dir, branch string, check func(dir string) error) error {
	if err := check(dir); err != nil {
		return fmt.Errorf("the check failed, so nothing was pushed: %w", err)
	}
	tree, err := s.checked(dir, branch)
	if err != nil {
		return err
	}
	sha, err := s.git(dir, "rev-parse", "HEAD")
	if err != nil {
		return err
	}
	if _, err := s.git(dir, "push", "-q", "-u", "origin", "HEAD:refs/heads/"+branch); err != nil {
		return err
	}
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/statuses/%s", s.Repo, sha),
		github.F("state", "success"), github.F("context", BatteryContext), github.F("description", BatteryDescription(tree))); err != nil {
		return fmt.Errorf("pushed %s, but posting its %s status failed, so CI runs the battery again: %w", branch, BatteryContext, err)
	}
	return nil
}

// checked answers the tree checked out in dir where it may be pushed: the
// battery passed it (battery.TreeFile), and origin/main, fetched again, is
// in it, so the push is one main's ruleset can merge as it stands.
func (s Source) checked(dir, branch string) (string, error) {
	tree, err := s.git(dir, "rev-parse", "HEAD^{tree}")
	if err != nil {
		return "", err
	}
	passed, ok, err := battery.Passed(s.Disk, dir)
	if err != nil {
		return "", err
	}
	if !ok || passed != tree {
		return "", fmt.Errorf("the battery has not passed %s's tree %s, so nothing was pushed: sh ./tests/check.sh records the tree it passed, from a clean worktree", branch, tree)
	}
	if _, err := s.git(dir, "fetch", "-q", "origin", "main"); err != nil {
		return "", err
	}
	if behind, err := s.behind(dir, "HEAD"); err != nil {
		return "", err
	} else if behind {
		return "", behindMain{branch}
	}
	return tree, nil
}

// behind says whether origin/main, as dir last fetched it, has a commit ref lacks.
func (s Source) behind(dir, ref string) (bool, error) {
	_, err := s.git(dir, "merge-base", "--is-ancestor", "origin/main", ref)
	if code, ok := proc.ExitCode(err); ok && code == 1 {
		return true, nil
	}
	return false, err
}

// commitStatus is the part of GitHub's commit status Trusted reads.
type commitStatus struct {
	State       string `json:"state"`
	Context     string `json:"context"`
	Description string `json:"description"`
	Creator     struct {
		Login string `json:"login"`
	} `json:"creator"`
}

// Trusted says why CI may trust the battery a box ran on commit sha, whose
// checkout holds tree: the commit's latest BatteryContext status is a
// success naming tree, posted by an account that writes to the repository.
// Where it may not, the error says why, and CI runs the battery itself. It is
// trust in one's own boxes, not a proof.
func (s Source) Trusted(sha, tree string) (string, error) {
	var st *commitStatus
	for k := 0; k < trustAsks && st == nil; k++ {
		if k > 0 {
			s.sleep(trustPause, fmt.Sprintf("the %s status on %s (ask %d of %d)", BatteryContext, sha, k+1, trustAsks))
		}
		// GitHub lists a commit's statuses newest first.
		all, err := api[commitStatus](s, fmt.Sprintf("repos/%s/commits/%s/statuses?per_page=100", s.Repo, sha), true)
		if err != nil {
			return "", err
		}
		for i := range all {
			if all[i].Context == BatteryContext {
				st = &all[i]
				break
			}
		}
	}
	switch {
	case st == nil:
		return "", fmt.Errorf("%s carries no %s status: no box's battery passed it", sha, BatteryContext)
	case st.State != "success":
		return "", fmt.Errorf("%s's %s status is %s, not success", sha, BatteryContext, st.State)
	case st.Description != BatteryDescription(tree):
		return "", fmt.Errorf("%s's %s status says %q, and its checkout holds tree %s", sha, BatteryContext, st.Description, tree)
	}
	perm, err := api[struct {
		Permission string `json:"permission"`
	}](s, fmt.Sprintf("repos/%s/collaborators/%s/permission", s.Repo, st.Creator.Login), false)
	if err != nil {
		return "", fmt.Errorf("reading what %s, who posted %s's %s status, may do: %w", st.Creator.Login, sha, BatteryContext, err)
	}
	if p := perm[0].Permission; p != "admin" && p != "write" {
		return "", fmt.Errorf("%s, who posted %s's %s status, has %s access to %s, not write", st.Creator.Login, sha, BatteryContext, p, s.Repo)
	}
	return fmt.Sprintf("%s passed the battery on tree %s, posted by %s, who writes to %s", sha, tree, st.Creator.Login, s.Repo), nil
}

// keptPull is the part of GitHub's pull request object Keep reads.
type keptPull struct {
	Number   int     `json:"number"`
	URL      string  `json:"html_url"`
	State    string  `json:"state"`
	MergedAt *string `json:"merged_at"`
}

// Kept is where the PR se issue keep keeps stands when it returns.
type Kept struct {
	Issue int    `json:"issue"`
	PR    int    `json:"pr"`
	URL   string `json:"url"`
	// Merged is true once the PR merged; TakenOver once another box took the
	// issue over. With neither, the PR is open and the time ran out: keep again.
	Merged    bool `json:"merged"`
	TakenOver bool `json:"taken_over"`
	// Updated counts the times it merged main in, checked and pushed.
	Updated int `json:"updated"`
}

// Keep keeps the PR of the issue branch checked out in dir until it merges,
// for within at most: whenever main has moved past the branch on origin, it
// merges origin/main in (never a rebase), runs check and pushes, as ship
// does, so CI starts on the push, trusts the battery and auto-merge merges
// it. It returns once the PR merged, once another box took the issue over
// (a takeover marker or another box's claim since it started), or once
// within ran out. A merge that conflicts, a check that fails and a PR closed
// unmerged are errors: the box fixes them and lands again.
func (s Source) Keep(dir string, within time.Duration, check func(dir string) error) (Kept, error) {
	n, err := s.issued(dir)
	if err != nil {
		return Kept{}, err
	}
	branch := Branch(n)
	k := Kept{Issue: n}
	start, err := s.marks(n)
	if err != nil {
		return k, err
	}
	end := s.Clock.Now().Add(within)
	owner, _, _ := strings.Cut(s.Repo, "/")
	for {
		pulls, err := api[keptPull](s, fmt.Sprintf("repos/%s/pulls?head=%s:%s&base=main&state=all&per_page=100", s.Repo, owner, branch), true)
		if err != nil {
			return k, err
		}
		if len(pulls) == 0 {
			return k, fmt.Errorf("%s has no PR to keep: land it first (se issue land)", branch)
		}
		p := pulls[0]
		for _, q := range pulls {
			if q.Number > p.Number {
				p = q
			}
		}
		k.PR, k.URL = p.Number, p.URL
		if p.MergedAt != nil {
			k.Merged = true
			return k, nil
		}
		if p.State != "open" {
			return k, fmt.Errorf("PR #%d (%s) was closed unmerged: land %s again, which opens a new one", p.Number, p.URL, branch)
		}
		m, err := s.marks(n)
		if err != nil {
			return k, err
		}
		if m.takeovers > start.takeovers || m.box != start.box {
			k.TakenOver = true
			return k, nil
		}
		if err := s.keepUp(dir, branch, check); err == nil {
			k.Updated++
		} else if !errors.Is(err, errUpToDate) && !errors.As(err, new(behindMain)) {
			// Main moving while the battery ran is tried again on the next look.
			return k, fmt.Errorf("PR #%d (%s) fell behind main: %w", p.Number, p.URL, err)
		}
		if !s.Clock.Now().Before(end) {
			return k, nil
		}
		s.sleep(keepPause, fmt.Sprintf("PR #%d to merge, or to fall behind main", p.Number))
	}
}

// errUpToDate is keepUp's answer for a branch main has not moved past.
var errUpToDate = errors.New("up to date with main")

// keepUp ships the branch checked out in dir where main has moved past
// origin's copy of it, and answers errUpToDate where it has not.
func (s Source) keepUp(dir, branch string, check func(dir string) error) error {
	if _, err := s.git(dir, "fetch", "-q", "origin", "main", "refs/heads/"+branch+":refs/remotes/origin/"+branch); err != nil {
		return err
	}
	behind, err := s.behind(dir, "origin/"+branch)
	if err != nil {
		return err
	}
	if !behind {
		return errUpToDate
	}
	if dirty, err := s.git(dir, "status", "--porcelain"); err != nil {
		return err
	} else if dirty != "" {
		return fmt.Errorf("%s has changes not committed, so nothing was merged or pushed:\n%s", dir, dirty)
	}
	return s.ship(dir, branch, check)
}
