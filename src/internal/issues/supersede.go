package issues

import (
	"fmt"
	"slices"
	"strings"

	"github.com/mb-89/SE/src/modules/io/github"
)

// Superseded is what Supersede did: the issue it closed and the successor
// that carries its work on.
type Superseded struct {
	// Issue is the superseded issue, now closed.
	Issue int `json:"issue"`
	// Successor is the final issue made in its place.
	Successor Issue `json:"successor"`
	// Parent is the parent the successor shares with it; zero for none.
	Parent int `json:"parent,omitempty"`
	// BlockedBy are its open blockers, which block the successor too.
	BlockedBy []int `json:"blocked_by"`
	// Blocks are its open dependents, now blocked by the successor.
	Blocks []int `json:"blocks,omitempty"`
	// Ready is true where nothing open blocks the successor.
	Ready bool `json:"ready"`
}

// Supersede is the second of the three ways a box closes the issue it took
// (the first is a PR, the third se issue close --fixed-by): issue n's
// successor, made through the same code as se issue new, carries n's title and text and the open questions the box could not
// answer, labelled se-final. It has n's parent and n's open blockers, and n's
// open dependents are linked as blocked by it. Then n closes, its comment
// naming the successor. A final issue is refused: its box lands a PR.
func (s Source) Supersede(n int, questions string) (Superseded, error) {
	if strings.TrimSpace(questions) == "" {
		return Superseded{}, fmt.Errorf("superseding #%d needs the open questions its box could not answer", n)
	}
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		if st := github.Status(err); st == 404 || st == 410 {
			return Superseded{}, fmt.Errorf("#%d does not exist in %s", n, s.Repo)
		}
		return Superseded{}, err
	}
	old := got[0]
	switch {
	case old.PullRequest != nil:
		return Superseded{}, fmt.Errorf("#%d is a pull request, not an issue", n)
	case old.State != "open":
		return Superseded{}, fmt.Errorf("#%d is closed already: only an open issue is superseded", n)
	case old.labelled(FinalLabel):
		return Superseded{}, fmt.Errorf("#%d is final (%s): it is never superseded again, its box lands a PR", n, FinalLabel)
	}
	parent, err := s.parentOf(n)
	if err != nil {
		return Superseded{}, err
	}
	blockers, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/dependencies/blocked_by?per_page=100", s.Repo, n), true)
	if err != nil {
		return Superseded{}, err
	}
	sup := Superseded{Issue: n, Parent: parent, BlockedBy: []int{}}
	for _, b := range blockers {
		if b.State == "open" {
			sup.BlockedBy = append(sup.BlockedBy, b.Number)
		}
	}
	if sup.Blocks, err = s.Dependents(n); err != nil {
		return Superseded{}, err
	}
	text := strings.TrimSpace(strings.ReplaceAll(old.Body, NewMark, ""))
	body := fmt.Sprintf("Supersedes #%d, whose box could not close it with a PR. This is its last attempt (%s): its box lands a PR.\n\n%s\n\n## Open questions\n%s",
		n, FinalLabel, text, strings.TrimSpace(questions))
	made, ready, err := s.Create(old.Title, body, parent, sup.BlockedBy, FinalLabel)
	if err != nil {
		return Superseded{}, err
	}
	sup.Successor, sup.Ready = made, ready
	if err := s.Blocking(made, sup.Blocks); err != nil {
		return sup, err
	}
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	comment := fmt.Sprintf("Superseded by #%d, which carries this issue on with the questions its box could not answer.\n%s", made.Number, made.URL)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", comment)); err != nil {
		return sup, fmt.Errorf("created #%d (%s), but commenting on #%d: %w", made.Number, made.URL, n, err)
	}
	if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", "not_planned")); err != nil {
		return sup, fmt.Errorf("created #%d (%s), but closing #%d: %w", made.Number, made.URL, n, err)
	}
	return sup, nil
}

// parentOf names the issue n is a sub-issue of, or zero where it is none.
func (s Source) parentOf(n int) (int, error) {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/parent", s.Repo, n), false)
	if err != nil {
		if github.Status(err) == 404 {
			return 0, nil
		}
		return 0, err
	}
	return got[0].Number, nil
}

// Duplicated is what CloseDuplicate did: the issue it closed and the open
// issue, or the merged pull request, that already covers it.
type Duplicated struct {
	// Issue is the duplicate, now closed.
	Issue int `json:"issue"`
	// Of is the open issue it duplicates, which carries the work on, or the
	// merged pull request that did its work.
	Of int `json:"of"`
	// URL is Of's link, or for a merged pull request its commit's.
	URL string `json:"url"`
	// Commit is the full SHA of the merged pull request's commit on main;
	// empty where Of is an issue.
	Commit string `json:"commit,omitempty"`
	// Blocks are the duplicate's open dependents, now blocked by Of.
	Blocks []int `json:"blocks,omitempty"`
	// Pulls are the duplicate's open PRs, now closed, each with a comment
	// naming Of.
	Pulls []int `json:"pulls,omitempty"`
	// Branch is the duplicate's issue-<n> claim, now deleted; empty where
	// origin held none.
	Branch string `json:"branch,omitempty"`
}

// mergedPull is the part of a pull request CloseDuplicate reads.
type mergedPull struct {
	State  string `json:"state"`
	Merged bool   `json:"merged"`
	SHA    string `json:"merge_commit_sha"`
	Title  string `json:"title"`
}

// CloseDuplicate is the supersede of an issue another open issue already covers,
// where its PR does the same work (se issue supersede n --duplicate-of of):
// it mints nothing. Issue n's open dependents are linked as blocked by of, so
// nothing that waited on n goes ahead early; then n closes as a duplicate
// (state_reason duplicate), its comment naming of. A final issue may close so
// too: the work it would land is landing under of. Before n closes, its open
// PR closes, a comment naming of, and its issue-<n> claim is deleted by a git
// push from dir (the boxes' proxy refuses the REST route), so no PR stays
// open with no issue behind it and se fleet fix finds no leftover claim.
//
// An issue duplicates only an open issue or a merged pull request, never an
// open one: an open PR may never merge, and the issue closed for it would
// count as handled while its work is not done (#438). Where of is a merged
// pull request, n's comment names its commit on main, as se issue close
// --fixed-by does, and nothing is linked: the work is done.
func (s Source) CloseDuplicate(dir string, n, of int) (Duplicated, error) {
	if n == of {
		return Duplicated{}, fmt.Errorf("#%d cannot duplicate itself", n)
	}
	got := map[int]issue{}
	for _, k := range []int{n, of} {
		one, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, k), false)
		if err != nil {
			if st := github.Status(err); st == 404 || st == 410 {
				return Duplicated{}, fmt.Errorf("#%d does not exist in %s", k, s.Repo)
			}
			return Duplicated{}, err
		}
		got[k] = one[0]
		switch {
		case one[0].PullRequest != nil && k == n:
			return Duplicated{}, fmt.Errorf("#%d is a pull request, not an issue", k)
		case one[0].PullRequest != nil:
			return s.duplicateOfPull(dir, n, of)
		case one[0].State != "open" && k == n:
			return Duplicated{}, fmt.Errorf("#%d is closed already: only an open issue is closed as a duplicate", n)
		case one[0].State != "open":
			return Duplicated{}, fmt.Errorf("#%d is closed: #%d duplicates only an open issue, which carries its work on, or a merged PR", of, n)
		}
	}
	dup := Duplicated{Issue: n, Of: of, URL: got[of].URL}
	deps, err := s.Dependents(n)
	if err != nil {
		return Duplicated{}, err
	}
	already, err := s.Dependents(of)
	if err != nil {
		return Duplicated{}, err
	}
	for _, d := range deps {
		if d != of && !slices.Contains(already, d) {
			dup.Blocks = append(dup.Blocks, d)
		}
	}
	for _, d := range dup.Blocks {
		if err := s.link(d, []int{of}, map[int]int64{of: got[of].ID}); err != nil {
			return dup, err
		}
	}
	if err := s.dropClaim(dir, &dup); err != nil {
		return dup, err
	}
	comment := fmt.Sprintf("Duplicate of #%d, which already covers this issue's work and carries it on.\n%s", of, got[of].URL)
	return dup, s.closeAsDuplicate(n, comment)
}

// duplicateOfPull closes the open issue n as a duplicate of the pull request
// of, which must be merged: an open one is refused, since it may never merge,
// and so is one closed unmerged. n's open PRs and claim go as for an issue,
// and its comment names the commit on main.
func (s Source) duplicateOfPull(dir string, n, of int) (Duplicated, error) {
	got, err := api[mergedPull](s, fmt.Sprintf("repos/%s/pulls/%d", s.Repo, of), false)
	if err != nil {
		return Duplicated{}, err
	}
	p := got[0]
	switch {
	case !p.Merged && p.State == "open":
		return Duplicated{}, fmt.Errorf("#%d is an open pull request: an issue is a duplicate only of an open issue or a merged PR, never of an open PR, which may never merge; name the issue it fixes", of)
	case !p.Merged:
		return Duplicated{}, fmt.Errorf("#%d is a pull request closed unmerged: its work is not on main, so #%d is no duplicate of it", of, n)
	case p.SHA == "":
		return Duplicated{}, fmt.Errorf("pull request #%d is merged but names no commit", of)
	}
	dup := Duplicated{Issue: n, Of: of, Commit: p.SHA, URL: fmt.Sprintf("https://github.com/%s/commit/%s", s.Repo, p.SHA)}
	if err := s.dropClaim(dir, &dup); err != nil {
		return dup, err
	}
	comment := fmt.Sprintf(fixedMark+"\nDuplicate of PR #%d, merged: its work is on main already, in %s (%s), so no PR lands it.\n%s",
		p.SHA, of, p.SHA[:min(len(p.SHA), 12)], p.Title, dup.URL)
	return dup, s.closeAsDuplicate(n, comment)
}

// closeAsDuplicate comments on issue n, then closes it as a duplicate.
func (s Source) closeAsDuplicate(n int, comment string) error {
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", comment)); err != nil {
		return fmt.Errorf("commenting on #%d: %w", n, err)
	}
	if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", "duplicate")); err != nil {
		return fmt.Errorf("closing #%d: %w", n, err)
	}
	return nil
}

// dropClaim closes the duplicate's open PRs, each with a comment naming the
// issue it duplicates, then deletes its issue-<n> branch where origin holds
// it, by a git push from dir. Run again, it finds nothing left to do.
func (s Source) dropClaim(dir string, dup *Duplicated) error {
	b := Branch(dup.Issue)
	open, err := s.openPulls(b)
	if err != nil {
		return err
	}
	for _, p := range open {
		body := fmt.Sprintf("Closed unmerged: #%d is a duplicate of #%d, which covers this work.\n%s", dup.Issue, dup.Of, dup.URL)
		if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, p.Number), github.F("body", body)); err != nil {
			return fmt.Errorf("commenting on PR #%d: %w", p.Number, err)
		}
		if _, err := s.GitHub.Send("PATCH", fmt.Sprintf("repos/%s/pulls/%d", s.Repo, p.Number), github.F("state", "closed")); err != nil {
			return fmt.Errorf("closing PR #%d: %w", p.Number, err)
		}
		dup.Pulls = append(dup.Pulls, p.Number)
	}
	held, err := s.git(dir, "ls-remote", "origin", "refs/heads/"+b)
	if err != nil {
		return fmt.Errorf("reading origin's %s: %w", b, err)
	}
	if strings.TrimSpace(held) == "" {
		return nil
	}
	if _, err := s.git(dir, "push", "-q", "origin", "--delete", b); err != nil {
		return fmt.Errorf("deleting %s: %w", b, err)
	}
	dup.Branch = b
	return nil
}
