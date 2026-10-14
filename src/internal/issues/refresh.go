package issues

import (
	"fmt"
	"path/filepath"
	"slices"
	"strings"
)

// A manifest's leaves branch from, and land into, its branch issue-<m>, so
// main's moves reach them only through it. Merged into it once, they reach
// every leaf through its landing; left out, each leaf meets them on its own,
// as conflicts (#503, #504, #505). So main is merged into each open
// manifest's branch as it moves, as se issue keep does for a PR: se fleet
// refresh, which the refresh workflow runs on every push to main, and se
// fleet fix, for what se fleet check finds behind.

// RefreshDir is where, under the checkout, a manifest's branch takes main in:
// git ignores .se/.runtime.
const RefreshDir = ".se/.runtime/refresh"

// Refreshed is one open manifest's branch, and what se fleet refresh did with it.
type Refreshed struct {
	Issue  int    `json:"issue"`
	Branch string `json:"branch"`
	// Merged is true where main was merged in and pushed; Conflict where the
	// merge conflicts, so nothing was pushed.
	Merged   bool `json:"merged"`
	Conflict bool `json:"conflict"`
	// Did says what was done, in a few words.
	Did string `json:"did"`
	// Failed is why the refresh failed, where it did; Did says so too.
	Failed string `json:"failed,omitempty"`
}

// Refresh merges origin's main into the branch of every open manifest that
// has one on origin and no open PR into main (se issue keep keeps that one),
// in a worktree of the checkout dir, never a rebase, and pushes it. A merge
// that conflicts pushes nothing and is answered as such, for se fleet check's
// stale manifest; a refresh that fails is reported, and the ones after it
// are still run.
func (s Source) Refresh(dir string) ([]Refreshed, error) {
	var manifests []issue
	var refs []ref
	var pulls []openPull
	if err := parallel([]func() error{
		func() (err error) {
			manifests, err = api[issue](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=open&per_page=100", s.Repo, ManifestLabel), true)
			return err
		},
		func() (err error) {
			refs, err = api[ref](s, fmt.Sprintf("repos/%s/git/matching-refs/heads/issue-", s.Repo), true)
			return err
		},
		func() (err error) {
			pulls, err = api[openPull](s, fmt.Sprintf("repos/%s/pulls?state=open&per_page=100", s.Repo), true)
			return err
		},
	}); err != nil {
		return nil, err
	}
	var ns []int
	for _, m := range manifests {
		if m.PullRequest == nil {
			ns = append(ns, m.Number)
		}
	}
	slices.Sort(ns)
	var out []Refreshed
	var failed []string
	for _, m := range refreshable(ns, refs, pulls) {
		r := s.refreshOne(dir, m.n)
		if r.Failed != "" {
			failed = append(failed, r.Branch)
		}
		out = append(out, r)
	}
	if len(failed) > 0 {
		return out, fmt.Errorf("could not refresh %s", strings.Join(failed, ", "))
	}
	return out, nil
}

// branchAt is a manifest and its branch's commit on origin.
type branchAt struct {
	n   int
	sha string
}

// refreshable is the manifests of ns, in their order, whose branch is on
// origin and has no open PR into main, each with its branch's commit.
func refreshable(ns []int, refs []ref, pulls []openPull) []branchAt {
	shas := map[string]string{}
	for _, r := range refs {
		shas[strings.TrimPrefix(r.Ref, "refs/heads/")] = r.Object.SHA
	}
	toMain := toMain(pulls)
	var out []branchAt
	for _, n := range ns {
		b := Branch(n)
		if _, open := toMain[b]; shas[b] != "" && !open {
			out = append(out, branchAt{n, shas[b]})
		}
	}
	return out
}

// refreshOne merges origin's main into manifest n's branch on origin, in a
// worktree it removes after, and pushes the merge.
func (s Source) refreshOne(dir string, n int) Refreshed {
	r := Refreshed{Issue: n, Branch: Branch(n)}
	if err := s.refreshIn(dir, &r); err != nil {
		r.Failed = err.Error()
		r.Did = "failed: " + r.Failed
	}
	return r
}

func (s Source) refreshIn(dir string, r *Refreshed) error {
	b := r.Branch
	if _, err := s.git(dir, "fetch", "-q", "origin", "main", "refs/heads/"+b+":refs/remotes/origin/"+b); err != nil {
		return err
	}
	if behind, err := s.behind(dir, "origin/"+b); err != nil || !behind {
		r.Did = "up to date with main"
		return err
	}
	wt := filepath.Join(dir, filepath.FromSlash(RefreshDir), b)
	_, _ = s.git(dir, "worktree", "remove", "--force", wt)
	if _, err := s.git(dir, "worktree", "add", "-q", "--detach", wt, "origin/"+b); err != nil {
		return err
	}
	defer func() { _, _ = s.git(dir, "worktree", "remove", "--force", wt) }()
	if _, err := s.git(wt, "merge", "-q", "--no-edit", "-m", "Merge origin/main into "+b+" (se fleet refresh)", "origin/main"); err != nil {
		if unmerged, _ := s.git(wt, "ls-files", "--unmerged"); unmerged == "" {
			return err
		}
		// A conflict in the battery's record alone is settled, as merge does.
		if !s.settle(wt) {
			r.Conflict = true
			r.Did = fmt.Sprintf("conflicts with main, so nothing was pushed: merge origin/main into %s by hand (never rebase), as se issue land of #%d does", b, r.Issue)
			return nil
		}
	}
	if _, err := s.git(wt, "push", "-q", "origin", "HEAD:refs/heads/"+b); err != nil {
		return err
	}
	r.Merged = true
	r.Did = "merged main in and pushed"
	return nil
}
