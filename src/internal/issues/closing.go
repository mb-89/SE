package issues

import (
	"fmt"
	"strings"
)

// Unclosed says what keeps the box that took issue n from ending: "" where n
// is closed (a merged PR, or a supersede) or its branch has an open PR with
// auto-merge on, else which of the two ways to close it is missing. It fails
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
	owner, _, _ := strings.Cut(s.Repo, "/")
	open, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls?head=%s:%s&base=main&state=open&per_page=100", s.Repo, owner, branch), true)
	if err != nil {
		return "", err
	}
	how := fmt.Sprintf("supersede it (se issue supersede %d --body-file F) with the questions you could not answer", n)
	if len(open) == 0 {
		return fmt.Sprintf("#%d is open with neither a PR from %s nor a supersede: land a PR (se issue land), or %s.", n, branch, how), nil
	}
	if open[0].AutoMerge != nil {
		return "", nil
	}
	return fmt.Sprintf("#%d is open and its PR #%d (%s) has auto-merge off: turn it on (se issue land), or %s.", n, open[0].Number, open[0].URL, how), nil
}
