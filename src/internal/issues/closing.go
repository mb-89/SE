package issues

import (
	"fmt"
	"strings"
)

// Unclosed says what keeps the box that took issue n from ending: "" where n
// is closed (a merged PR, a supersede, or se issue close --fixed-by) or its branch has an open PR with
// auto-merge on, else which of the ways to close it is missing. It fails
// closed: only what GitHub shows lets the box end.
func (s Source) Unclosed(n int) (string, error) {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		return "", err
	}
	if got[0].State != "open" {
		return "", nil
	}
	branch := Branch(n)
	open, err := s.openPulls(branch)
	if err != nil {
		return "", err
	}
	how := fmt.Sprintf("supersede it (se issue supersede %d --body-file F) with the questions you could not answer, or, where its work is on main already, close it naming the commit (se issue close %d --fixed-by SHA --answers FILE)", n, n)
	if len(open) == 0 {
		return fmt.Sprintf("#%d is open with neither a PR from %s nor a supersede: land a PR (se issue land), or %s.", n, branch, how), nil
	}
	if open[0].AutoMerge != nil {
		return "", nil
	}
	return fmt.Sprintf("#%d is open and its PR #%d (%s) has auto-merge off: turn it on (se issue land), or %s.", n, open[0].Number, open[0].URL, how), nil
}

// openPulls is the open PRs from branch against main.
func (s Source) openPulls(branch string) ([]openPull, error) {
	owner, _, _ := strings.Cut(s.Repo, "/")
	return api[openPull](s, fmt.Sprintf("repos/%s/pulls?head=%s:%s&base=main&state=open&per_page=100", s.Repo, owner, branch), true)
}
