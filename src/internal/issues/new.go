package issues

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/mb-89/SE/src/internal/io/github"
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
			if st := github.Status(err); st == 404 || st == 410 {
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
		if _, err := s.GitHub.Send("POST", path, github.Int("issue_id", ids[b])); err != nil {
			return fmt.Errorf("linking #%d as blocked by #%d: %w", n, b, err)
		}
	}
	return nil
}

// Exist refuses, naming it, any of numbers that is no issue of the
// repository, or a pull request; it writes nothing.
func (s Source) Exist(numbers []int) error {
	_, err := s.ids(numbers)
	return err
}

// Blocking links each of dependents as blocked by made, an issue se just
// created, through GitHub's native links: what is left of a box's issue holds
// up only those of its dependents that need it. Call Exist on dependents
// before creating made, so a wrong number creates nothing.
func (s Source) Blocking(made Issue, dependents []int) error {
	for _, n := range dependents {
		if err := s.link(n, []int{made.Number}, map[int]int64{made.Number: made.id}); err != nil {
			return fmt.Errorf("created #%d (%s), but %w", made.Number, made.URL, err)
		}
	}
	return nil
}

// Dependents names the open issues issue n blocks, GitHub's "blocking"
// links, lowest first: what waits for n to close.
func (s Source) Dependents(n int) ([]int, error) {
	native, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/dependencies/blocking?per_page=100", s.Repo, n), true)
	if err != nil {
		return nil, err
	}
	out := []int{}
	for _, d := range native {
		if d.State == "open" {
			out = append(out, d.Number)
		}
	}
	sort.Ints(out)
	return out, nil
}

// Create opens a fleet issue, labelled se and each of labels (se-review,
// se-final), makes it a sub-issue of parent where that is above zero, and
// links it as blocked by each of blockedBy. The
// parent and the blockers are checked before the issue is created, so naming
// an issue that does not exist creates nothing. ready is true when nothing
// blocks the created issue: each of blockedBy is closed already.
func (s Source) Create(title, body string, parent int, blockedBy []int, labels ...string) (made Issue, ready bool, err error) {
	return s.create(title, body, parent, blockedBy, append([]string{Label}, labels...))
}

// create is Create with the labels given, se among them. The body ends in
// NewMark. There are no bare issues: one filed into no parent goes into the
// open misc manifest (FileInto), unless it stands at the top by itself (a
// manifest, a retro, an overhaul or an issue for a person).
func (s Source) create(title, body string, parent int, blockedBy []int, labels []string) (made Issue, ready bool, err error) {
	if err := titled(title); err != nil {
		return Issue{}, false, err
	}
	ids, ready, err := s.lookup(blockedBy)
	if err != nil {
		return Issue{}, false, err
	}
	if parent == 0 && !atTop(labels) {
		if parent, err = s.FileInto(); err != nil {
			return Issue{}, false, err
		}
	}
	if parent > 0 {
		if _, err := s.ids([]int{parent}); err != nil {
			return Issue{}, false, err
		}
	}
	path := fmt.Sprintf("repos/%s/issues", s.Repo)
	fields := []github.Field{github.F("title", title), github.F("body", marked(body))}
	for _, l := range labels {
		fields = append(fields, github.F("labels[]", l))
	}
	out, err := s.GitHub.Send("POST", path, fields...)
	if err != nil {
		return Issue{}, false, err
	}
	var i issue
	if err := json.Unmarshal(out, &i); err != nil || i.Number == 0 {
		return Issue{}, false, fmt.Errorf("gh api %s answered no issue: %v", path, err)
	}
	created := Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL, id: i.ID, in: parent}
	if parent > 0 {
		if err := s.subIssue(parent, i.ID); err != nil {
			return created, false, fmt.Errorf("created #%d (%s), but making it a sub-issue of #%d: %w", i.Number, i.URL, parent, err)
		}
	}
	if err := s.link(i.Number, blockedBy, ids); err != nil {
		return created, false, fmt.Errorf("created #%d (%s), but %w", i.Number, i.URL, err)
	}
	return created, ready, nil
}

// subIssue makes the issue GitHub knows by id a sub-issue of parent.
func (s Source) subIssue(parent int, id int64) error {
	_, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/sub_issues", s.Repo, parent), github.Int("sub_issue_id", id))
	return err
}

// titled refuses a title that is empty or only spaces.
func titled(title string) error {
	if strings.TrimSpace(title) == "" {
		return fmt.Errorf("an issue needs a --title")
	}
	return nil
}

// marked is body as se writes every issue's body: its text, then NewMark
// alone at its end. The mark tells the retro the issue was written here, not
// by hand; a mark the text carries already is moved to the end, not doubled.
func marked(body string) string {
	return strings.TrimRight(strings.ReplaceAll(body, NewMark, ""), " \n") + "\n\n" + NewMark
}

// Duplicate names the lowest open fleet issue titled title, its spaces
// trimmed, that is a sub-issue of parent, or at the top where parent is 0;
// 0 where there is none. It reads the fleet as CloseParents does, closing the
// parents it closes, so se issue new reads it once.
func (s Source) Duplicate(title string, parent int) (int, error) {
	return s.duplicate(title, parent, 0)
}

// duplicate is Duplicate, issue except left out: an issue retitled is no
// duplicate of itself.
func (s Source) duplicate(title string, parent, except int) (int, error) {
	t, err := s.load(nil)
	if err != nil {
		return 0, err
	}
	title = strings.TrimSpace(title)
	for _, n := range t.numbers() {
		if n != except && strings.TrimSpace(t.byNum[n].Title) == title && t.above[n] == parent {
			return n, nil
		}
	}
	return 0, nil
}
