// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
)

// closeIssue closes issue n on the fake GitHub, as a merged PR would.
func closeIssue(t *testing.T, gh github.GitHub, n int) {
	t.Helper()
	if _, err := gh.Send("PATCH", fmt.Sprintf("repos/o/r/issues/%d", n), github.F("state", "closed"), github.F("state_reason", "completed")); err != nil {
		t.Fatal(err)
	}
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
	t.Parallel()
	w := Worker{Session: "s1", Workspace: "/b/issue-2"}
	gh := recorded(t, map[string]string{"repos/o/r/issues/2": `{"number":2}`, "repos/o/r/issues/3": `{"number":3}`})
	s := Source{Proc: machineOf(t), Repo: repo, GitHub: gh, Clock: atNow()}
	if err := s.record(2, w); err != nil {
		t.Fatal(err)
	}
	if c := commentsAt(t, gh, 2); len(c) != 1 || !strings.Contains(c[0].Body, `<!-- se-worker {"session":"s1","workspace":"/b/issue-2"} -->`) {
		t.Fatalf("%+v", c)
	}
	if got, err := s.workers(2); err != nil || !reflect.DeepEqual(got, []Worker{w}) {
		t.Fatalf("%v %v", got, err)
	}
	if err := s.record(2, w); err != nil || len(gh.Writes()) != 1 {
		t.Fatalf("%v %q", err, gh.Writes())
	}
	// Without a session there is no one to record.
	if err := s.record(3, Worker{Workspace: "/b"}); err != nil || len(gh.Writes()) != 1 {
		t.Fatalf("%v %q", err, gh.Writes())
	}
}

func TestAReviewIsDoneByAnAgentThatWorkedNoneOfTheTree(t *testing.T) {
	t.Parallel()
	worker := Worker{Session: "box", Workspace: "/b/issue-2"}
	fixer := Worker{Session: "box2", Workspace: "/c/issue-3"}
	reviewer := Worker{Session: "box", Workspace: "/b/review-1-1"}
	answers := map[string]string{
		// #1, labelled se-review, holds one work leaf, #2.
		listPath:    list(node(1, 1, ReviewLabel), node(2, 0)),
		refsPath:    `[]`,
		subsPath(1): subs(2),
	}
	gh := recorded(t, answers)
	s := Source{Proc: machineOf(t), Repo: repo, GitHub: gh, Clock: atNow()}

	// Before the leaf lands, #1 is not ready for review.
	if tr, err := s.In(1); err != nil || !reflect.DeepEqual(numbers(tr.Ready), []int{2}) || len(tr.Review) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}
	if _, err := s.Review(1, reviewer, true, passing); err == nil || !strings.Contains(err.Error(), "not ready for review") {
		t.Fatalf("%v", err)
	}

	// The leaf lands: its worker is recorded, and it closes.
	seed(t, gh, map[string]string{commentsPath(2): workedBy(worker)})
	closeIssue(t, gh, 2)
	tr, err := s.In(1)
	if err != nil || !reflect.DeepEqual(numbers(tr.Review), []int{1}) || len(tr.Ready) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}
	if got := tr.ReviewWorktree("/b/SE", 1); got != "git fetch -q origin main && git worktree add --detach /b/review-1-1 origin/main" {
		t.Fatal(got)
	}

	// The leaf's worker may not review it.
	landed := len(gh.Writes())
	if _, err := s.Review(1, worker, true, passing); err == nil || !strings.Contains(err.Error(), "session box in /b/issue-2 worked #2 in #1's tree") {
		t.Fatalf("%v", err)
	}
	if w := gh.Writes()[landed:]; len(w) != 0 {
		t.Fatalf("a refused review wrote %q", w)
	}

	// Another agent fails it: the findings go on #1, a fix leaf under it,
	// the repository's next issue, #3.
	r, err := s.Review(1, reviewer, false, failing("fix it"))
	if err != nil || r.Passed || !reflect.DeepEqual(numbers(r.Fixes), []int{3}) {
		t.Fatalf("%+v %v", r, err)
	}
	// The blocking finding is an se-final sub-issue of #1; the report goes on #1.
	want := []string{"POST repos/o/r/issues", "POST repos/o/r/issues/1/sub_issues", "POST repos/o/r/issues/1/comments"}
	if w := gh.Writes()[landed:]; !reflect.DeepEqual(w, want) {
		t.Fatalf("%q", w)
	}
	fix := issueAt(t, gh, 3)
	if fix.Title != "fix it" || !strings.HasPrefix(fix.Body, "Blocking: the review of #1 waits for it") || !fix.labelled(Label) || !fix.labelled(FinalLabel) {
		t.Fatalf("%+v", fix)
	}
	if c := commentsAt(t, gh, 1); len(c) != 1 || !strings.HasPrefix(c[0].Body, "## Review: FAIL\n\nBy session box in /b/review-1-1, at c0ffee.") ||
		!strings.Contains(c[0].Body, "- **fix it** (blocking, #3)") || !strings.Contains(c[0].Body, `<!-- se:review {"passed":false,"rereview":false,`) {
		t.Fatalf("%+v", c)
	}

	// The fix is work inside #1, which waits for it.
	if tr, err := s.In(1); err != nil || !reflect.DeepEqual(numbers(tr.Ready), []int{3}) || len(tr.Review) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}

	// Once the fix has landed, #1 is ready for review again, in a new worktree.
	seed(t, gh, map[string]string{commentsPath(3): workedBy(fixer)})
	closeIssue(t, gh, 3)
	if tr, err := s.In(1); err != nil || !reflect.DeepEqual(numbers(tr.Review), []int{1}) || !strings.HasSuffix(tr.ReviewWorktree("/b/SE", 1), "/b/review-1-2 origin/main") {
		t.Fatalf("%+v %v", tr, err)
	}
	// Its review is a re-review: it checks the earlier blocker, #3.
	again := passing
	again.Requirements = []Requirement{{Item: "fix it is fixed", Evidence: "go test ./... ok", Blocker: 3}}
	if _, err := s.Review(1, reviewer, true, passing); err == nil || !strings.Contains(err.Error(), "checks only the earlier blockers (#3)") {
		t.Fatalf("%v", err)
	}
	if _, err := s.Review(1, fixer, true, again); err == nil || !strings.Contains(err.Error(), "worked #3") {
		t.Fatalf("%v", err)
	}

	// A pass by a different agent closes it.
	fixed := len(gh.Writes())
	r, err = s.Review(1, reviewer, true, again)
	if err != nil || !r.Passed || len(r.Fixes) != 0 {
		t.Fatalf("%+v %v", r, err)
	}
	if w := gh.Writes()[fixed:]; !reflect.DeepEqual(w, []string{"POST repos/o/r/issues/1/comments", "PATCH repos/o/r/issues/1"}) {
		t.Fatalf("%q", w)
	}
	if c := commentsAt(t, gh, 1); !strings.HasPrefix(c[len(c)-1].Body, "## Re-review: PASS\n") || issueAt(t, gh, 1).State != "closed" || issueAt(t, gh, 1).StateReason != "completed" {
		t.Fatalf("%+v", c)
	}
}

func TestAPassClosesTheParentItCompletes(t *testing.T) {
	t.Parallel()
	answers := map[string]string{
		// #1 holds only #2, a review parent ready for review.
		listPath:        list(node(1, 1), node(2, 1, ReviewLabel)),
		refsPath:        `[]`,
		subsPath(1):     subs(2),
		subsPath(2):     subs(-3),
		commentsPath(3): workedBy(Worker{Session: "a", Workspace: "/w"}),
	}
	gh := recorded(t, answers)
	s := Source{Repo: repo, GitHub: gh, Clock: atNow()}
	// Closing #2 closes #1, its last open sub-issue, too.
	if _, err := s.Review(2, Worker{Session: "b", Workspace: "/w"}, true, passing); err != nil {
		t.Fatal(err)
	}
	if w := gh.Writes(); w[len(w)-1] != "PATCH repos/o/r/issues/1" || issueAt(t, gh, 1).State != "closed" {
		t.Fatalf("%q", w)
	}
}

func TestAReviewRefusesWhatItCannotTell(t *testing.T) {
	t.Parallel()
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
	gh := recorded(t, answers)
	s := Source{Proc: machineOf(t), Repo: repo, GitHub: gh, Clock: atNow()}
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
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused review wrote %q", w)
	}
	// With #3's worker recorded, w's workspace in another session may review.
	seed(t, gh, map[string]string{commentsPath(3): workedBy(Worker{Session: "w", Workspace: "/w3"})})
	if _, err := s.Review(1, Worker{Session: "other", Workspace: "/w"}, true, passing); err != nil {
		t.Fatal(err)
	}
}

func TestTheReviewerModelIsOneLineOfSpecModels(t *testing.T) {
	t.Parallel()
	d, dir := disk.NewFake(), filepath.FromSlash("/checkout")
	if got := ReviewerModel(d, dir); got != "" {
		t.Fatalf("without the file: %q", got)
	}
	if err := d.MkdirAll(filepath.Join(dir, "spec")); err != nil {
		t.Fatal(err)
	}
	if err := d.WriteFile(filepath.Join(dir, ModelsPath), []byte("# models\nbox: opus\nreviewer: \"fable\" # stronger\n")); err != nil {
		t.Fatal(err)
	}
	if got := ReviewerModel(d, dir); got != "fable" {
		t.Fatalf("%q", got)
	}
	// The repository's own setting is never empty: it is the checkout's file, on the real disk.
	if got := ReviewerModel(disk.Real(), "../../.."); got == "" {
		t.Fatal("spec/models.yaml sets no reviewer")
	}
}
