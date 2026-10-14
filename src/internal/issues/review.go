package issues

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"

	"github.com/mb-89/SE/src/internal/io/github"
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
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n), github.F("body", body)); err != nil {
		return fmt.Errorf("recording who worked #%d: %w", n, err)
	}
	return nil
}

// Reviewed is what a review did.
type Reviewed struct {
	Issue  int  `json:"issue"`
	Passed bool `json:"passed"`
	// Fixes are the issues the blocking findings became: se-final sub-issues
	// of the gate, so it is reviewed again once they have landed.
	Fixes []Issue `json:"fixes"`
	// Filed are the issues the non-blocking findings became, se-final, in
	// the normal queue; Unfiled counts those past the first issues/config/max-filed.
	Filed   []Issue `json:"filed"`
	Unfiled int     `json:"unfiled"`
	// Accepted are the earlier blockers a re-review found the problem of
	// again: each was a final attempt, so the repeat is accepted, files
	// nothing and blocks no more.
	Accepted []int `json:"accepted,omitempty"`
	// Closed is set where the review closed n: it passed, or every blocking
	// finding was an accepted repeat.
	Closed bool `json:"closed"`
}

// Review passes or fails issue n, a parent labelled se-review whose
// sub-issues are all closed, as reviewer, with its report rep. It refuses a
// reviewer who worked any leaf of n's tree, a tree with a leaf whose worker is
// not recorded, and a report that breaks the rules of spec/review.md (see
// Report.check). Every verified finding becomes an se-final issue: a blocking
// one a sub-issue of n, a non-blocking one in the open misc manifest, at most
// issues/config/max-filed of them. The report goes on n with its machine-readable block; a
// pass closes n, which can complete its parent, except a manifest at the
// top: its se-review label comes off, and the one PR it lands as closes it.
// A blocking finding that repeats an earlier blocker is an accepted repeat:
// it files nothing, and a fail whose blocking findings are all repeats ends
// n's review as a pass does.
func (s Source) Review(n int, reviewer Worker, pass bool, rep Report) (Reviewed, error) {
	if reviewer.Session == "" {
		return Reviewed{}, fmt.Errorf("%s is not set, so this reviewer cannot be told apart from the workers of #%d's tree; nothing was reviewed", SessionVar, n)
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
	earlier, err := s.lastVerdict(n)
	if err != nil {
		return Reviewed{}, err
	}
	if err := rep.check(pass, earlier.blockers()); err != nil {
		return Reviewed{}, err
	}
	if err := s.separate(n, n, reviewer); err != nil {
		return Reviewed{}, err
	}
	r := Reviewed{Issue: n, Passed: pass, Fixes: []Issue{}, Filed: []Issue{}}
	for k := range rep.Findings {
		f := &rep.Findings[k]
		switch {
		case f.Repeats > 0:
			r.Accepted = append(r.Accepted, f.Repeats)
			continue
		case !f.Blocking && len(r.Filed) == s.config().MaxFiled:
			r.Unfiled++
			continue
		}
		parent := 0
		if f.Blocking {
			parent = n
		}
		made, _, err := s.Create(f.Title, f.body(n), parent, nil, FinalLabel)
		if err != nil {
			return r, err
		}
		f.Issue = made.Number
		if f.Blocking {
			r.Fixes = append(r.Fixes, made)
		} else {
			r.Filed = append(r.Filed, made)
		}
	}
	v := Verdict{Passed: pass, Rereview: earlier.failed(), Unfiled: r.Unfiled, Report: rep}
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", v.render(reviewer, s.config().MaxFiled))); err != nil {
		return r, fmt.Errorf("posting the report on #%d: %w", n, err)
	}
	if pass || !rep.blocks() {
		// A manifest passed is not closed: its leaves' work is on its
		// branch, and it lands as one PR, which closes it.
		if got, err := api[issue](s, path, false); err != nil {
			return r, err
		} else if got[0].labelled(ManifestLabel) {
			if top, err := s.manifestOf(n); err != nil {
				return r, err
			} else if top == 0 {
				if _, err := s.GitHub.Send("DELETE", path+"/labels/"+ReviewLabel); err != nil {
					return r, fmt.Errorf("taking %s off #%d: %w", ReviewLabel, n, err)
				}
				return r, nil
			}
		}
		if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", "completed")); err != nil {
			return r, fmt.Errorf("closing #%d: %w", n, err)
		}
		r.Closed = true
		return r, s.CloseParents()
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
