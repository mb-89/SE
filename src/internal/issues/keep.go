package issues

import (
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// The owner's rule, 2026-10-14: a box stays with its PR until it merges, it
// pushes only what is checked, and CI trusts the
// battery the box already ran. se issue land and se issue keep push through
// ship, which commits the battery's record of the tree it passed
// (battery.Passed) with the work; CI's check job asks battery.Trusted about
// it (se fleet trust) and runs the battery only where the record does not
// name the tree it checked out.

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
// branch main has moved past since, commits the battery's record and pushes.
func (s Source) ship(dir, branch string, check func(dir string) error) error {
	if err := s.takeIn(dir, branch); err != nil {
		return err
	}
	return s.push(dir, branch, check, nil)
}

// push is ship after takeIn: it runs check, refuses a tree the battery did
// not pass and a branch main has moved past since, commits the battery's
// record of the pass, so the pushed commit holds it, runs before (where
// set), and pushes. before writes what must survive a stop after it: se
// issue land's landing answers.
func (s Source) push(dir, branch string, check func(dir string) error, before func() error) error {
	if err := check(dir); err != nil {
		return fmt.Errorf("the check failed, so nothing was pushed: %w", err)
	}
	tree, err := s.checked(dir, branch)
	if err != nil {
		return err
	}
	if err := battery.Commit(s.Proc, dir, tree); err != nil {
		return err
	}
	if before != nil {
		if err := before(); err != nil {
			return err
		}
	}
	_, err = s.git(dir, "push", "-q", "-u", "origin", "HEAD:refs/heads/"+branch)
	return err
}

// checked answers the tree checked out in dir where it may be pushed: the
// battery passed it (its record, staged here, names it), and origin/main,
// fetched again, is in it, so the push is one main's ruleset can merge as it
// stands.
func (s Source) checked(dir, branch string) (string, error) {
	tree, err := battery.TreeOf(s.Proc, dir, "HEAD")
	if err != nil {
		return "", err
	}
	passed, ok, err := battery.Stage(s.Proc, dir)
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

// merge merges ref into the branch checked out in dir, the battery's record
// first put back as HEAD holds it (the battery runs again on the merge). A
// conflict in that record alone is settled, since every branch writes its
// own; any other conflict is undone.
func (s Source) merge(dir, ref string) error {
	if err := battery.Reset(s.Proc, dir); err != nil {
		return err
	}
	_, err := s.git(dir, "merge", "-q", "--no-edit", ref)
	if err == nil {
		return nil
	}
	if s.settle(dir) {
		return nil
	}
	_, _ = s.git(dir, "merge", "--abort")
	return err
}

// settle commits the merge in dir where it conflicts in the battery's record
// alone (battery.Resolve), and answers false where any other path conflicts.
func (s Source) settle(dir string) bool {
	if settled, err := battery.Resolve(s.Proc, dir); err != nil || !settled {
		return false
	}
	_, err := s.git(dir, "commit", "-q", "--no-edit")
	return err == nil
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
	if dirty, err := battery.Dirty(s.Proc, dir); err != nil {
		return err
	} else if dirty != "" {
		return fmt.Errorf("%s has changes not committed, so nothing was merged or pushed:\n%s", dir, dirty)
	}
	return s.ship(dir, branch, check)
}
