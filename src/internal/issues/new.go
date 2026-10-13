package issues

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// ParseBlockedBy reads --blocked-by: a comma-separated list of issue numbers,
// "5,8" or "#5, #8", or the word none. An empty value is refused, so a
// dependency is always declared, never forgotten.
func ParseBlockedBy(s string) ([]int, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil, fmt.Errorf("--blocked-by is required: issue numbers, like 5,8, or none")
	}
	if s == "none" {
		return nil, nil
	}
	seen := map[int]bool{}
	var out []int
	for _, w := range strings.Split(s, ",") {
		n, err := strconv.Atoi(strings.TrimPrefix(strings.TrimSpace(w), "#"))
		if err != nil || n <= 0 {
			return nil, fmt.Errorf("--blocked-by takes issue numbers, like 5,8, or none, not %q", s)
		}
		if !seen[n] {
			seen[n] = true
			out = append(out, n)
		}
	}
	sort.Ints(out)
	return out, nil
}

// lookup is the part of an issue a link is written with.
type lookup struct {
	ID          int64            `json:"id"`
	Number      int              `json:"number"`
	State       string           `json:"state"`
	PullRequest *json.RawMessage `json:"pull_request"`
}

// ids reads each issue's id, which the link endpoints take in place of its
// number; an issue that does not exist, or a pull request, is refused.
func (s Source) ids(numbers []int) (map[int]int64, error) {
	out, _, err := s.lookup(numbers)
	return out, err
}

// lookup is ids, and also says whether every one of the issues is closed.
func (s Source) lookup(numbers []int) (map[int]int64, bool, error) {
	out := map[int]int64{}
	closed := true
	for _, n := range numbers {
		got, err := api[lookup](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
		if err != nil {
			if strings.Contains(err.Error(), "HTTP 404") || strings.Contains(err.Error(), "HTTP 410") {
				return nil, false, fmt.Errorf("#%d does not exist in %s", n, s.Repo)
			}
			return nil, false, err
		}
		if got[0].PullRequest != nil {
			return nil, false, fmt.Errorf("#%d is a pull request, not an issue", n)
		}
		out[n] = got[0].ID
		closed = closed && got[0].State == "closed"
	}
	return out, closed, nil
}

// Block adds GitHub's native "blocked by" link from issue n to each of
// blockers. It refuses, before writing anything, a blocker that does not
// exist. This is the one place se writes dependencies.
func (s Source) Block(n int, blockers []int) error {
	ids, err := s.ids(blockers)
	if err != nil {
		return err
	}
	return s.link(n, blockers, ids)
}

func (s Source) link(n int, blockers []int, ids map[int]int64) error {
	for _, b := range blockers {
		if b == n {
			return fmt.Errorf("#%d cannot block itself", n)
		}
		path := fmt.Sprintf("repos/%s/issues/%d/dependencies/blocked_by", s.Repo, n)
		if _, err := s.GH("api", "-X", "POST", "-F", fmt.Sprintf("issue_id=%d", ids[b]), path); err != nil {
			return fmt.Errorf("linking #%d as blocked by #%d: %w", n, b, err)
		}
	}
	return nil
}

// Create opens a fleet issue, labelled se (and se-review where review is
// true), makes it a sub-issue of parent where that is above zero, and links it
// as blocked by each of blockedBy. The
// parent and the blockers are checked before the issue is created, so naming
// an issue that does not exist creates nothing. ready is true when nothing
// blocks the created issue: each of blockedBy is closed already.
func (s Source) Create(title, body string, parent int, blockedBy []int, review bool) (made Issue, ready bool, err error) {
	labels := []string{Label}
	if review {
		labels = append(labels, ReviewLabel)
	}
	return s.create(title, body, parent, blockedBy, labels)
}

// create is Create with the labels given, se among them. The body ends in
// NewMark.
func (s Source) create(title, body string, parent int, blockedBy []int, labels []string) (made Issue, ready bool, err error) {
	if strings.TrimSpace(title) == "" {
		return Issue{}, false, fmt.Errorf("an issue needs a --title")
	}
	ids, ready, err := s.lookup(blockedBy)
	if err != nil {
		return Issue{}, false, err
	}
	if parent > 0 {
		if _, err := s.ids([]int{parent}); err != nil {
			return Issue{}, false, err
		}
	}
	path := fmt.Sprintf("repos/%s/issues", s.Repo)
	// The mark tells the retro this issue was made here, not by hand.
	args := []string{"api", "-X", "POST", "-f", "title=" + title, "-f", "body=" + strings.TrimRight(body, "\n") + "\n\n" + NewMark}
	for _, l := range labels {
		args = append(args, "-f", "labels[]="+l)
	}
	out, err := s.GH(append(args, path)...)
	if err != nil {
		return Issue{}, false, err
	}
	var i issue
	if err := json.Unmarshal(out, &i); err != nil || i.Number == 0 {
		return Issue{}, false, fmt.Errorf("gh api %s answered no issue: %v", path, err)
	}
	created := Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL}
	if parent > 0 {
		path := fmt.Sprintf("repos/%s/issues/%d/sub_issues", s.Repo, parent)
		if _, err := s.GH("api", "-X", "POST", "-F", fmt.Sprintf("sub_issue_id=%d", i.ID), path); err != nil {
			return created, false, fmt.Errorf("created #%d (%s), but making it a sub-issue of #%d: %w", i.Number, i.URL, parent, err)
		}
	}
	if err := s.link(i.Number, blockedBy, ids); err != nil {
		return created, false, fmt.Errorf("created #%d (%s), but %w", i.Number, i.URL, err)
	}
	return created, ready, nil
}
