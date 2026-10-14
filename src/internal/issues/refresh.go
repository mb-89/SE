package issues

import (
	"fmt"
	"strings"

	"github.com/mb-89/SE/src/internal/io/github"
)

// CIWorkflow is the workflow se fleet refresh starts on a PR it updated: the
// repository's token, which the update is made with, starts no workflow by
// its pushes.
const CIWorkflow = "ci.yml"

// waits is how often a PR is asked for its new head after an update.
const waits = 10

// Refreshed is one open PR, auto-merge on, that was behind main.
type Refreshed struct {
	PR     int    `json:"pr"`
	Branch string `json:"branch"`
	// Head is the PR's head after the update; the head it had where it was not updated.
	Head string `json:"head"`
	// Did says what was done, in a few words.
	Did string `json:"did"`
	// Failed is why the update failed, where it did; Did says so too.
	Failed string `json:"failed,omitempty"`
}

// Refresh merges main into every open PR against main whose auto-merge is on
// and whose head main has moved past, through GitHub's update-branch, and
// starts CIWorkflow on its new head: the main ruleset merges a PR only when
// it is up to date with main, so this keeps auto-merge moving. A PR that
// conflicts with main is left to its takeover (se issue pull --take). A PR
// whose update fails is reported, and the ones after it are still updated.
func (s Source) Refresh() ([]Refreshed, error) {
	pulls, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls?base=main&state=open&per_page=100", s.Repo), true)
	if err != nil {
		return nil, err
	}
	var out []Refreshed
	var failed []string
	for _, p := range pulls {
		if p.AutoMerge == nil {
			continue
		}
		cmp, err := api[struct {
			BehindBy int `json:"behind_by"`
		}](s, fmt.Sprintf("repos/%s/compare/main...%s?per_page=1", s.Repo, p.Head.SHA), false)
		if err != nil {
			return out, err
		}
		if cmp[0].BehindBy == 0 {
			continue
		}
		r := Refreshed{PR: p.Number, Branch: p.Head.Ref, Head: p.Head.SHA}
		if p, err = s.mergeability(p); err != nil {
			return out, err
		}
		if p.dirty() {
			r.Did = "left to its takeover: it conflicts with main"
			out = append(out, r)
			continue
		}
		if err := s.update(&r); err != nil {
			r.Failed = err.Error()
			r.Did = "failed: " + r.Failed
			failed = append(failed, fmt.Sprintf("PR #%d", r.PR))
		}
		out = append(out, r)
	}
	if len(failed) > 0 {
		return out, fmt.Errorf("could not bring %s up to date with main", strings.Join(failed, ", "))
	}
	return out, nil
}

// update merges main into r's branch, waits until GitHub shows the new head,
// and starts CIWorkflow on the branch.
func (s Source) update(r *Refreshed) error {
	old := r.Head
	if _, err := s.GitHub.Send("PUT", fmt.Sprintf("repos/%s/pulls/%d/update-branch", s.Repo, r.PR), github.F("expected_head_sha", old)); err != nil {
		return err
	}
	for k := 0; k < waits && r.Head == old; k++ {
		s.sleep(pause, fmt.Sprintf("GitHub to show PR #%d's new head (ask %d of %d)", r.PR, k+1, waits))
		got, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls/%d", s.Repo, r.PR), false)
		if err != nil {
			return err
		}
		r.Head = got[0].Head.SHA
	}
	if r.Head == old {
		return fmt.Errorf("GitHub took the update, but PR #%d's head is still %s", r.PR, old)
	}
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/actions/workflows/%s/dispatches", s.Repo, CIWorkflow), github.F("ref", r.Branch)); err != nil {
		return fmt.Errorf("merged main into %s at %s, but could not start %s: %w", r.Branch, r.Head, CIWorkflow, err)
	}
	r.Did = fmt.Sprintf("merged main in at %s and started %s", r.Head, CIWorkflow)
	return nil
}
