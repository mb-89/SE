package issues

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"
)

// SessionVar is the environment variable that names the Claude Code session
// an agent runs in.
const SessionVar = "CLAUDE_CODE_SESSION_ID"

// Worker is who works a leaf or reviews a tree: the session it runs in and
// the workspace it runs from. Sub-agents of one box share a session, and each
// works in its own worktree, so the two together tell them apart.
type Worker struct {
	Session   string `json:"session"`
	Workspace string `json:"workspace"`
}

func (w Worker) String() string { return fmt.Sprintf("session %s in %s", w.Session, w.Workspace) }

// workerMark is how a leaf's comment records its worker.
var workerMark = regexp.MustCompile(`<!-- se-worker (\{.*?\}) -->`)

// workers reads who worked issue n from its comments.
func (s Source) workers(n int) ([]Worker, error) {
	comments, err := api[struct {
		Body string `json:"body"`
	}](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return nil, err
	}
	var out []Worker
	for _, c := range comments {
		for _, m := range workerMark.FindAllStringSubmatch(c.Body, -1) {
			var w Worker
			if json.Unmarshal([]byte(m[1]), &w) == nil && w.Session != "" {
				out = append(out, w)
			}
		}
	}
	return out, nil
}

// record writes on leaf n that w worked it, unless that is recorded already.
// Without a session there is no one to record.
func (s Source) record(n int, w Worker) error {
	if w.Session == "" {
		return nil
	}
	have, err := s.workers(n)
	if err != nil {
		return err
	}
	for _, h := range have {
		if h == w {
			return nil
		}
	}
	mark, err := json.Marshal(w)
	if err != nil {
		return err
	}
	body := fmt.Sprintf("Worked by %s.\n\n<!-- se-worker %s -->", w, mark)
	if _, err := s.GH("api", "-X", "POST", "-f", "body="+body, fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n)); err != nil {
		return fmt.Errorf("recording who worked #%d: %w", n, err)
	}
	return nil
}

// Reviewed is what a review did.
type Reviewed struct {
	Issue  int  `json:"issue"`
	Passed bool `json:"passed"`
	// Fixes are the fix leaves a failed review created under the issue.
	Fixes []Issue `json:"fixes"`
}

// Review passes or fails issue n, a parent labelled se-review whose
// sub-issues are all closed, as reviewer. It refuses a reviewer who worked any
// leaf of n's tree, and a tree with a leaf whose worker is not recorded. A pass
// posts why as a comment and closes n, which can complete its parent; a fail
// posts why and creates one fix leaf under n per title in fixes, so n is ready
// for review again once they have landed.
func (s Source) Review(n int, reviewer Worker, pass bool, why string, fixes []string) (Reviewed, error) {
	switch {
	case strings.TrimSpace(why) == "":
		return Reviewed{}, fmt.Errorf("a review needs --why: the verdict, or the findings")
	case pass && len(fixes) > 0:
		return Reviewed{}, fmt.Errorf("a pass takes no --fix")
	case !pass && len(fixes) == 0:
		return Reviewed{}, fmt.Errorf("a fail needs a --fix for each fix leaf it creates")
	case reviewer.Session == "":
		return Reviewed{}, fmt.Errorf("%s is not set, so this reviewer cannot be told apart from the workers of #%d's tree; nothing was reviewed", SessionVar, n)
	}
	for _, f := range fixes {
		if strings.TrimSpace(f) == "" {
			return Reviewed{}, fmt.Errorf("a --fix needs a title")
		}
	}
	all, t, err := s.survey()
	if err != nil {
		return Reviewed{}, err
	}
	var st *Status
	for k := range all {
		if all[k].Number == n {
			st = &all[k]
		}
	}
	switch {
	case st == nil:
		return Reviewed{}, fmt.Errorf("#%d is not an open issue labelled %s", n, Label)
	case !t.byNum[n].labelled(ReviewLabel):
		return Reviewed{}, fmt.Errorf("#%d is not labelled %s, so it is not reviewed", n, ReviewLabel)
	case !st.Review && st.Why != "":
		return Reviewed{}, fmt.Errorf("#%d is not ready for review: %s", n, st.Why)
	case !st.Review:
		return Reviewed{}, fmt.Errorf("#%d is not ready for review: its sub-issues are not all closed", n)
	}
	if err := s.separate(n, n, reviewer); err != nil {
		return Reviewed{}, err
	}
	r := Reviewed{Issue: n, Passed: pass, Fixes: []Issue{}}
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	if pass {
		if _, err := s.GH("api", "-X", "POST", "-f", fmt.Sprintf("body=Review passed, by %s.\n\n%s", reviewer, why), path+"/comments"); err != nil {
			return r, fmt.Errorf("posting the verdict on #%d: %w", n, err)
		}
		if _, err := s.GH("api", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=completed", path); err != nil {
			return r, fmt.Errorf("closing #%d: %w", n, err)
		}
		return r, s.CloseParents()
	}
	for _, f := range fixes {
		made, err := s.Create(f, fmt.Sprintf("A fix the review of #%d asks for. Its findings:\n\n%s", n, why), n, nil, false)
		if err != nil {
			return r, err
		}
		r.Fixes = append(r.Fixes, made)
	}
	names := make([]string, len(r.Fixes))
	for k, f := range r.Fixes {
		names[k] = fmt.Sprintf("- #%d %s", f.Number, f.Title)
	}
	body := fmt.Sprintf("Review failed, by %s.\n\n%s\n\nFixes:\n%s", reviewer, why, strings.Join(names, "\n"))
	if _, err := s.GH("api", "-X", "POST", "-f", "body="+body, path+"/comments"); err != nil {
		return r, fmt.Errorf("posting the findings on #%d: %w", n, err)
	}
	return r, nil
}

// separate refuses reviewer where it worked a leaf of n's tree, open or
// closed, at any depth; root is the issue under review. A leaf closed as not
// planned or as a duplicate landed no work.
func (s Source) separate(root, n int, reviewer Worker) error {
	subs, err := api[struct {
		issue
		Reason string `json:"state_reason"`
	}](s, fmt.Sprintf("repos/%s/issues/%d/sub_issues?per_page=100", s.Repo, n), true)
	if err != nil {
		return err
	}
	for _, c := range subs {
		if c.SubIssues != nil && c.SubIssues.Total > 0 {
			if err := s.separate(root, c.Number, reviewer); err != nil {
				return err
			}
			continue
		}
		if c.Reason == "not_planned" || c.Reason == "duplicate" {
			continue
		}
		ws, err := s.workers(c.Number)
		if err != nil {
			return err
		}
		if len(ws) == 0 {
			return fmt.Errorf("#%d in #%d's tree records no worker (se issue land records one), so who may review #%d cannot be told; nothing was reviewed", c.Number, root, root)
		}
		for _, w := range ws {
			if w.Session == reviewer.Session && filepath.Clean(w.Workspace) == filepath.Clean(reviewer.Workspace) {
				return fmt.Errorf("%s worked #%d in #%d's tree, and a review is done by an agent that worked none of it; nothing was reviewed", reviewer, c.Number, root)
			}
		}
	}
	return nil
}

// ReviewWorktree is the command that makes a fresh worktree of origin/main,
// beside the checkout dir, for the reviewer of n in round, the count of n's
// sub-issues: each failed review adds fixes, so each round gets its own.
func ReviewWorktree(dir string, n, round int) string {
	return fmt.Sprintf("git fetch -q origin main && git worktree add --detach %s origin/main",
		filepath.Join(filepath.Dir(dir), fmt.Sprintf("review-%d-%d", n, round)))
}
