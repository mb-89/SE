package issues

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mb-89/SE/src/internal/io/github"
)

// Ruled is one open se PR into main, its head merged with main and checked
// against se rules.
type Ruled struct {
	PR     int    `json:"pr"`
	Branch string `json:"branch"`
	// Head is the PR's head that was merged with main.
	Head string `json:"head"`
	// Findings is what se rules found on the merge, one per line; empty, none.
	Findings string `json:"findings,omitempty"`
	// Did says what was done, in a few words.
	Did string `json:"did"`
	// Failed is why the check failed, where it did; Did says so too.
	Failed string `json:"failed,omitempty"`
}

// rulesMark records on a PR the findings it was told of, by their hash, so
// the same findings are told once.
var rulesMark = regexp.MustCompile(`<!-- se:rules ([0-9a-f]+) -->`)

// issueBranch is the head branch of an se PR.
var issueBranch = regexp.MustCompile(`^issue-\d+$`)

// RulesDir is where, under the checkout, each PR's merge with main is checked
// out: git ignores .se/.runtime.
const RulesDir = ".se/.runtime/rules"

// Rules merges the head of every open se PR into main (an issue-<n> branch)
// with origin's main in a worktree of the checkout dir, and runs check on
// the merge, which answers se rules' findings on it, empty where there are
// none. On each PR whose merge breaks a rule it comments the findings and
// what to do, once for the same findings: a rule main took breaks the PRs
// opened before it, and the box that owns one acts on that comment before
// its CI goes red. A PR that conflicts with main is left to its takeover. A
// PR whose check fails is reported, and the ones after it are still checked.
func (s Source) Rules(dir string, check func(dir string) (string, error)) ([]Ruled, error) {
	if _, err := s.git(dir, "fetch", "-q", "origin", "main"); err != nil {
		return nil, err
	}
	main, err := s.git(dir, "rev-parse", "FETCH_HEAD")
	if err != nil {
		return nil, err
	}
	pulls, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls?base=main&state=open&per_page=100", s.Repo), true)
	if err != nil {
		return nil, err
	}
	var out []Ruled
	var failed []string
	for _, p := range pulls {
		if !issueBranch.MatchString(p.Head.Ref) {
			continue
		}
		r := Ruled{PR: p.Number, Branch: p.Head.Ref, Head: p.Head.SHA}
		if err := s.ruleOne(dir, main, &r, check); err != nil {
			r.Failed = err.Error()
			r.Did = "failed: " + r.Failed
			failed = append(failed, fmt.Sprintf("PR #%d", r.PR))
		}
		out = append(out, r)
	}
	if len(failed) > 0 {
		return out, fmt.Errorf("could not check %s against se rules", strings.Join(failed, ", "))
	}
	return out, nil
}

// ruleOne checks r's head merged with main, in a worktree it removes after,
// and comments the findings on r's PR.
func (s Source) ruleOne(dir, main string, r *Ruled, check func(dir string) (string, error)) error {
	if _, err := s.git(dir, "fetch", "-q", "origin", r.Branch); err != nil {
		return err
	}
	head, err := s.git(dir, "rev-parse", "FETCH_HEAD")
	if err != nil {
		return err
	}
	r.Head = head
	wt := filepath.Join(dir, filepath.FromSlash(RulesDir), r.Branch)
	_, _ = s.git(dir, "worktree", "remove", "--force", wt)
	if _, err := s.git(dir, "worktree", "add", "-q", "--detach", wt, main); err != nil {
		return err
	}
	defer func() { _, _ = s.git(dir, "worktree", "remove", "--force", wt) }()
	// The merge is never committed, but git asks for a name to merge under,
	// which a workflow's checkout has none of.
	if _, err := s.git(wt, "-c", "user.name=se", "-c", "user.email=se@localhost", "merge", "-q", "--no-commit", "--no-ff", head); err != nil {
		if unmerged, _ := s.git(wt, "ls-files", "--unmerged"); unmerged == "" {
			return err
		}
		r.Did = "left to its takeover: it conflicts with main"
		return nil
	}
	if r.Findings, err = check(wt); err != nil {
		return err
	}
	if r.Findings == "" {
		r.Did = "passes se rules merged with main"
		return nil
	}
	sum := sha256.Sum256([]byte(r.Findings))
	key := hex.EncodeToString(sum[:6])
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, r.PR), true)
	if err != nil {
		return err
	}
	for _, c := range comments {
		for _, m := range rulesMark.FindAllStringSubmatch(c.Body, -1) {
			if m[1] == key {
				r.Did = "breaks se rules merged with main, as it was told already"
				return nil
			}
		}
	}
	body := fmt.Sprintf("Main took a change to se's rules (main at %s), and this PR's head %s, merged with main, breaks them:\n\n```\n%s\n```\n\n"+
		"Merge origin/main into %s (never rebase, never force-push), fix these, and land it again with se issue land, before its CI goes red.\n\n<!-- se:rules %s -->",
		main, head, r.Findings, r.Branch, key)
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, r.PR), github.F("body", body)); err != nil {
		return fmt.Errorf("commenting on PR #%d: %w", r.PR, err)
	}
	r.Did = "breaks se rules merged with main: told on the PR what to fix"
	return nil
}
