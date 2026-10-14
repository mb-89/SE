// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// reviewGH answers from answers, which a test changes as the tree moves; an
// issue's links and comments it holds no answer for are none. It keeps every
// write it was asked.
func reviewGH(t *testing.T, answers map[string]string) (GH, *[][]string) {
	t.Helper()
	var wrote [][]string
	return func(args ...string) ([]byte, error) {
		path := args[len(args)-1]
		if args[1] == "-X" {
			wrote = append(wrote, args)
		}
		if a, ok := answers[path]; ok {
			return []byte(a), nil
		}
		if strings.HasSuffix(path, "/dependencies/blocked_by?per_page=100") || strings.HasSuffix(path, "/comments?per_page=100") {
			return []byte(`[]`), nil
		}
		t.Fatalf("gh %v was not recorded", args)
		return nil, nil
	}, &wrote
}

// passing is a report a pass may post: every requirement has its evidence.
var passing = Report{
	Commit:       "c0ffee",
	Requirements: []Requirement{{Item: "it holds", Evidence: "go test ./... ok"}},
	Clean:        []string{"the tests: none weakened"},
}

// failing is passing with one blocking finding.
func failing(title string) Report {
	r := passing
	r.Findings = []ReviewFinding{{Title: title, Evidence: "x.go:3", Blocking: true, Why: "it breaks"}}
	return r
}

func commentsPath(n int) string { return fmt.Sprintf("repos/o/r/issues/%d/comments?per_page=100", n) }

// workedBy is the comments of a leaf that w landed.
func workedBy(w Worker) string {
	mark, _ := json.Marshal(w)
	return fmt.Sprintf(`[{"body":"Worked by %s.\n\n<!-- se-worker %s -->"}]`, w, strings.ReplaceAll(string(mark), `"`, `\"`))
}

func TestRecordWritesTheWorkerOnce(t *testing.T) {
	w := Worker{Session: "s1", Workspace: "/b/issue-2"}
	answers := map[string]string{"repos/o/r/issues/2/comments": `{}`}
	gh, wrote := reviewGH(t, answers)
	s := Source{Repo: repo, GH: gh, Clock: atNow()}
	if err := s.record(2, w); err != nil {
		t.Fatal(err)
	}
	if len(*wrote) != 1 || !strings.Contains((*wrote)[0][4], `<!-- se-worker {"session":"s1","workspace":"/b/issue-2"} -->`) {
		t.Fatalf("%q", *wrote)
	}
	answers[commentsPath(2)] = workedBy(w)
	if got, err := s.workers(2); err != nil || !reflect.DeepEqual(got, []Worker{w}) {
		t.Fatalf("%v %v", got, err)
	}
	if err := s.record(2, w); err != nil || len(*wrote) != 1 {
		t.Fatalf("%v %q", err, *wrote)
	}
	// Without a session there is no one to record.
	if err := s.record(3, Worker{Workspace: "/b"}); err != nil || len(*wrote) != 1 {
		t.Fatalf("%v %q", err, *wrote)
	}
}

func TestAReviewIsDoneByAnAgentThatWorkedNoneOfTheTree(t *testing.T) {
	worker := Worker{Session: "box", Workspace: "/b/issue-2"}
	fixer := Worker{Session: "box2", Workspace: "/c/issue-3"}
	reviewer := Worker{Session: "box", Workspace: "/b/review-1-1"}
	answers := map[string]string{
		// #1, labelled se-review, holds one work leaf, #2.
		listPath:    list(node(1, 1, ReviewLabel), node(2, 0)),
		refsPath:    `[]`,
		subsPath(1): subs(2),
	}
	gh, wrote := reviewGH(t, answers)
	s := Source{Repo: repo, GH: gh, Clock: atNow()}

	// Before the leaf lands, #1 is not ready for review.
	if tr, err := s.In(1); err != nil || !reflect.DeepEqual(numbers(tr.Ready), []int{2}) || len(tr.Review) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}
	if _, err := s.Review(1, reviewer, true, passing); err == nil || !strings.Contains(err.Error(), "not ready for review") {
		t.Fatalf("%v", err)
	}

	// The leaf lands: its worker is recorded, and it closes.
	answers[listPath] = list(node(1, 1, ReviewLabel))
	answers[subsPath(1)] = subs(-2)
	answers[commentsPath(2)] = workedBy(worker)
	tr, err := s.In(1)
	if err != nil || !reflect.DeepEqual(numbers(tr.Review), []int{1}) || len(tr.Ready) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}
	if got := tr.ReviewWorktree("/b/SE", 1); got != "git fetch -q origin main && git worktree add --detach /b/review-1-1 origin/main" {
		t.Fatal(got)
	}

	// The leaf's worker may not review it.
	if _, err := s.Review(1, worker, true, passing); err == nil || !strings.Contains(err.Error(), "session box in /b/issue-2 worked #2 in #1's tree") {
		t.Fatalf("%v", err)
	}
	if len(*wrote) != 0 {
		t.Fatalf("a refused review wrote %q", *wrote)
	}

	// Another agent fails it: the findings go on #1, a fix leaf under it.
	answers["repos/o/r/issues/1"] = `{"id":1001,"number":1}`
	answers["repos/o/r/issues"] = `{"id":1003,"number":3,"title":"fix it","html_url":"u3"}`
	answers["repos/o/r/issues/1/sub_issues"] = `{}`
	answers["repos/o/r/issues/1/comments"] = `{}`
	r, err := s.Review(1, reviewer, false, failing("fix it"))
	if err != nil || r.Passed || !reflect.DeepEqual(numbers(r.Fixes), []int{3}) {
		t.Fatalf("%+v %v", r, err)
	}
	// The blocking finding is an se-final sub-issue of #1; the report goes on #1.
	if w := *wrote; len(w) != 3 ||
		!reflect.DeepEqual(w[0][:4], []string{"api", "-X", "POST", "-f"}) || w[0][4] != "title=fix it" ||
		!strings.HasPrefix(w[0][6], "body=Blocking: the review of #1 waits for it") ||
		!reflect.DeepEqual(w[0][7:], []string{"-f", "labels[]=se", "-f", "labels[]=se-final", "repos/o/r/issues"}) ||
		!reflect.DeepEqual(w[1], []string{"api", "-X", "POST", "-F", "sub_issue_id=1003", "repos/o/r/issues/1/sub_issues"}) ||
		w[2][5] != "repos/o/r/issues/1/comments" ||
		!strings.HasPrefix(w[2][4], "body=## Review: FAIL\n\nBy session box in /b/review-1-1, at c0ffee.") ||
		!strings.Contains(w[2][4], "- **fix it** (blocking, #3)") ||
		!strings.Contains(w[2][4], `<!-- se:review {"passed":false,"rereview":false,`) {
		t.Fatalf("%q", w)
	}
	*wrote = nil

	// The fix is work inside #1, which waits for it.
	answers[listPath] = list(node(1, 2, ReviewLabel), node(3, 0))
	answers[subsPath(1)] = subs(-2, 3)
	if tr, err := s.In(1); err != nil || !reflect.DeepEqual(numbers(tr.Ready), []int{3}) || len(tr.Review) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}

	// Once the fix has landed, #1 is ready for review again, in a new worktree.
	answers[listPath] = list(node(1, 2, ReviewLabel))
	answers[subsPath(1)] = subs(-2, -3)
	answers[commentsPath(3)] = workedBy(fixer)
	if tr, err := s.In(1); err != nil || !reflect.DeepEqual(numbers(tr.Review), []int{1}) || !strings.HasSuffix(tr.ReviewWorktree("/b/SE", 1), "/b/review-1-2 origin/main") {
		t.Fatalf("%+v %v", tr, err)
	}
	if _, err := s.Review(1, fixer, true, passing); err == nil || !strings.Contains(err.Error(), "worked #3") {
		t.Fatalf("%v", err)
	}

	// A pass by a different agent closes it.
	r, err = s.Review(1, reviewer, true, passing)
	if err != nil || !r.Passed || len(r.Fixes) != 0 {
		t.Fatalf("%+v %v", r, err)
	}
	if w := *wrote; len(w) != 2 || w[0][5] != "repos/o/r/issues/1/comments" || !strings.HasPrefix(w[0][4], "body=## Review: PASS\n") ||
		!reflect.DeepEqual(w[1], []string{"api", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=completed", "repos/o/r/issues/1"}) {
		t.Fatalf("%q", w)
	}
}

func TestAPassClosesTheParentItCompletes(t *testing.T) {
	answers := map[string]string{
		// #1 holds only #2, a review parent ready for review.
		listPath:                      list(node(1, 1), node(2, 1, ReviewLabel)),
		refsPath:                      `[]`,
		subsPath(1):                   subs(2),
		subsPath(2):                   subs(-3),
		commentsPath(3):               workedBy(Worker{Session: "a", Workspace: "/w"}),
		"repos/o/r/issues/2/comments": `{}`,
		"repos/o/r/issues/2":          `{}`,
		"repos/o/r/issues/1/comments": `{}`,
		"repos/o/r/issues/1":          `{}`,
	}
	gh, wrote := reviewGH(t, answers)
	s := Source{Repo: repo, GH: gh, Clock: atNow()}
	// The closing is read back before the parent-closing rule runs.
	closing := gh
	s.GH = func(args ...string) ([]byte, error) {
		if args[len(args)-1] == "repos/o/r/issues/2" && args[1] == "-X" {
			answers[listPath] = list(node(1, 1))
			answers[subsPath(1)] = subs(-2)
		}
		return closing(args...)
	}
	if _, err := s.Review(2, Worker{Session: "b", Workspace: "/w"}, true, passing); err != nil {
		t.Fatal(err)
	}
	last := (*wrote)[len(*wrote)-1]
	if want := []string{"api", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=completed", "repos/o/r/issues/1"}; !reflect.DeepEqual(last, want) {
		t.Fatalf("%q", *wrote)
	}
}

func TestAReviewRefusesWhatItCannotTell(t *testing.T) {
	answers := map[string]string{
		// #1 is ready for review: #2 is a closed parent holding #4 (worked
		// by w) and #5 (closed as not planned); #3 records no worker. #7 is
		// a leaf without the label.
		listPath:        list(node(1, 2, ReviewLabel), node(7, 0)),
		refsPath:        `[]`,
		subsPath(1):     `[{"number":2,"state":"closed","sub_issues_summary":{"total":2}},{"number":3,"state":"closed","state_reason":"completed"}]`,
		subsPath(2):     `[{"number":4,"state":"closed"},{"number":5,"state":"closed","state_reason":"not_planned"}]`,
		commentsPath(4): workedBy(Worker{Session: "w", Workspace: "/w"}),
	}
	gh, wrote := reviewGH(t, answers)
	s := Source{Repo: repo, GH: gh, Clock: atNow()}
	r := Worker{Session: "r", Workspace: "/r"}
	for _, c := range []struct {
		n    int
		who  Worker
		pass bool
		rep  Report
		want string
	}{
		{1, Worker{Workspace: "/r"}, true, passing, SessionVar + " is not set"},
		{9, r, true, passing, "#9 is not an open issue labelled se"},
		{7, r, true, passing, "#7 is not labelled se-review"},
		{1, r, true, passing, "#3 in #1's tree records no worker"},
		{1, Worker{Session: "w", Workspace: "/w/"}, true, passing, "worked #4 in #1's tree"},
	} {
		if _, err := s.Review(c.n, c.who, c.pass, c.rep); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%+v: %v", c, err)
		}
	}
	if len(*wrote) != 0 {
		t.Fatalf("a refused review wrote %q", *wrote)
	}
	// With #3's worker recorded, w's workspace in another session may review.
	answers[commentsPath(3)] = workedBy(Worker{Session: "w", Workspace: "/w3"})
	answers["repos/o/r/issues/1/comments"] = `{}`
	answers["repos/o/r/issues/1"] = `{}`
	if _, err := s.Review(1, Worker{Session: "other", Workspace: "/w"}, true, passing); err != nil {
		t.Fatal(err)
	}
}

func TestTheReviewerModelIsOneLineOfSpecModels(t *testing.T) {
	dir := t.TempDir()
	if got := ReviewerModel(dir); got != "" {
		t.Fatalf("without the file: %q", got)
	}
	if err := os.MkdirAll(filepath.Join(dir, "spec"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, ModelsPath), []byte("# models\nbox: opus\nreviewer: \"fable\" # stronger\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := ReviewerModel(dir); got != "fable" {
		t.Fatalf("%q", got)
	}
	// The repository's own setting is never empty.
	if got := ReviewerModel("../../.."); got == "" {
		t.Fatal("spec/models.yaml sets no reviewer")
	}
}
