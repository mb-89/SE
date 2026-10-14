// Internal test package: it drives the unexported claimTree.
package issues

import (
	"fmt"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// node is an open se issue with subs sub-issues; labels are its labels beyond se.
func node(n, subs int, labels ...string) string {
	ls := `{"name":"se"}`
	for _, l := range labels {
		ls += fmt.Sprintf(`,{"name":%q}`, l)
	}
	return fmt.Sprintf(`{"id":%d,"number":%d,"title":"t%d","state":"open","html_url":"u%d","labels":[%s],"sub_issues_summary":{"total":%d}}`,
		1000+n, n, n, n, ls, subs)
}

// subs lists sub-issues as GitHub does: "5" is open, "-5" closed.
func subs(ns ...int) string {
	var out []string
	for _, n := range ns {
		state := "open"
		if n < 0 {
			n, state = -n, "closed"
		}
		out = append(out, fmt.Sprintf(`{"number":%d,"state":%q}`, n, state))
	}
	return "[" + strings.Join(out, ",") + "]"
}

// inTree is recorded: an issue's links it holds no answer for are none, as
// the fake GitHub answers for an issue it knows.
func inTree(t *testing.T, answers map[string]string) *github.Fake {
	t.Helper()
	return recorded(t, answers)
}

func subsPath(n int) string { return fmt.Sprintf("repos/o/r/issues/%d/sub_issues?per_page=100", n) }

func blockedPath(n int) string {
	return fmt.Sprintf("repos/o/r/issues/%d/dependencies/blocked_by?per_page=100", n)
}

func list(nodes ...string) string { return "[" + strings.Join(nodes, ",") + "]" }

func TestASubIssueIsNeverOfferedAtTheTop(t *testing.T) {
	t.Parallel()
	answers := map[string]string{
		// #1 is a parent of #2 and #3; #4 stands alone.
		listPath:    list(node(3, 0), node(2, 0), node(1, 2), node(4, 0)),
		refsPath:    `[]`,
		subsPath(1): subs(2, 3),
	}
	gh := inTree(t, answers)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	next, ok, err := s.Next()
	if err != nil || !ok || next.Number != 1 || !next.Parent {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
	if _, _, err := s.Take(t.TempDir(), 2); err == nil || !strings.Contains(err.Error(), "#2 is a sub-issue of #1") {
		t.Fatalf("%v", err)
	}
	// With the parent blocked, its sub-issues are still not offered, nor #4,
	// a bare leaf: boxes take only manifests.
	seed(t, gh, map[string]string{listPath: list(node(3, 0), node(2, 0), node(1, 2), node(4, 0))})
	seed(t, gh, map[string]string{blockedPath(1): subs(9)})
	if next, ok, err := s.Next(); err != nil || ok {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
	if _, _, err := s.Take(t.TempDir(), 4); err == nil || !strings.Contains(err.Error(), "#4 is not ready: "+BareWhy) {
		t.Fatalf("%v", err)
	}
}

func TestInOffersTheReadyLeavesAtAnyDepth(t *testing.T) {
	t.Parallel()
	answers := map[string]string{
		listPath: list(
			node(10, 6),  // the root
			node(11, 0),  // blocked by #30, outside the tree
			node(12, 1),  // a parent blocked by #40, outside
			node(13, 0),  // inside #12, so held by #12's blocker
			node(14, 0),  // blocked by #11, inside
			node(15, 0),  // claimed
			node(16, 0),  // its blocker #17 is closed
			node(18, 1),  // a parent whose leaf #19 is ready
			node(19, 0),  // two levels down
			node(20, 1),  // another tree
			node(21, 0),  // inside #20
			node(30, 0),  // at the top
			node(40, 0),  // at the top
			node(50, 1),  // a root blocked by #30
			node(51, 0)), // inside #50, so held by its root's blocker
		refsPath:        `[{"ref":"refs/heads/issue-15"},{"ref":"refs/heads/issue-10"}]`,
		openPullsPath:   `[]`,
		subsPath(10):    subs(11, 12, 14, 15, 16, 18, -17),
		subsPath(12):    subs(13),
		subsPath(18):    subs(19),
		subsPath(20):    subs(21),
		subsPath(50):    subs(51),
		blockedPath(11): subs(30),
		blockedPath(12): subs(40),
		blockedPath(14): subs(11),
		blockedPath(16): subs(-17),
		blockedPath(50): subs(30),
		activity(15):    pushed(fresh),
	}
	gh := inTree(t, answers)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	all, err := s.Survey()
	if err != nil {
		t.Fatal(err)
	}
	why := map[int]string{}
	for _, st := range all {
		why[st.Number] = st.Why
	}
	want := map[int]string{
		10: "", 11: "blocked by #30", 12: "blocked by #40", 13: "#12 is blocked by #40", 14: "blocked by #11",
		15: "claimed by issue-15", 16: "", 18: "", 19: "", 20: "", 21: "", 30: "", 40: "",
		50: "blocked by #30", 51: "#50 is blocked by #30",
	}
	if !reflect.DeepEqual(why, want) {
		t.Fatalf("%v\nwant %v", why, want)
	}
	tr, err := s.In(10)
	if err != nil {
		t.Fatal(err)
	}
	if got := numbers(tr.Ready); !reflect.DeepEqual(got, []int{16, 19}) || len(tr.Review) != 0 || tr.Closed {
		t.Fatalf("%+v", tr)
	}
	// A claimed parent is picked up again: its claim does not hold it.
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 10 {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
	if tr, err := s.In(12); err != nil || len(tr.Ready) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}
	if tr, err := s.In(50); err != nil || len(tr.Ready) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}
}

func numbers(is []Issue) []int {
	var out []int
	for _, i := range is {
		out = append(out, i.Number)
	}
	return out
}

func TestParentsCloseByThemselvesDeepestFirst(t *testing.T) {
	t.Parallel()
	gh := recorded(t, map[string]string{
		// #1 holds #2 and a closed #3; #2 holds only closed sub-issues, so
		// once #2 closes, #1 does too. #6 still has an open sub-issue.
		listPath:    list(node(1, 2), node(2, 2), node(6, 2), node(7, 0)),
		subsPath(1): subs(2, -3),
		subsPath(2): subs(-4, -5),
		subsPath(6): subs(7, -8),
	})
	if err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}).CloseParents(); err != nil {
		t.Fatal(err)
	}
	want := []string{"POST repos/o/r/issues/2/comments", "PATCH repos/o/r/issues/2", "POST repos/o/r/issues/1/comments", "PATCH repos/o/r/issues/1"}
	if w := gh.Writes(); !reflect.DeepEqual(w, want) {
		t.Fatalf("%q\nwant %q", w, want)
	}
	for _, n := range []int{1, 2} {
		i, c := issueAt(t, gh, n), commentsAt(t, gh, n)
		if i.State != "closed" || i.StateReason != "completed" || len(c) != 1 || c[0].Body != fmt.Sprintf("All sub-issues of #%d are closed, so it closes by itself.", n) {
			t.Fatalf("#%d: %+v %+v", n, i, c)
		}
	}
	if i := issueAt(t, gh, 6); i.State != "open" {
		t.Fatalf("#6 closed: %+v", i)
	}
}

func TestAReviewParentNeverClosesByItself(t *testing.T) {
	t.Parallel()
	answers := map[string]string{
		// #1 is the root; #2, labelled se-review, has only closed sub-issues;
		// #5 waits on #2.
		listPath:       list(node(1, 2), node(2, 2, ReviewLabel), node(5, 0)),
		refsPath:       `[]`,
		subsPath(1):    subs(2, 5),
		subsPath(2):    subs(-3, -4),
		blockedPath(5): subs(2),
	}
	gh := inTree(t, answers)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()} // a write would not be recorded
	tr, err := s.In(1)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(numbers(tr.Review), []int{2}) || len(tr.Ready) != 0 || tr.Closed {
		t.Fatalf("%+v", tr)
	}
	// No leaf is ready, but the review is, so the root is offered: a box takes
	// the tree and its coordinator starts the reviewer. The review itself is
	// never taken as a leaf.
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 1 || !next.Parent {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
	if _, _, _, err := s.TakeIn(t.TempDir(), 1, 2); err == nil || !strings.Contains(err.Error(), "a parent holds no work") {
		t.Fatalf("%v", err)
	}
	// With the review parent blocked, nothing in the tree is offered.
	seed(t, gh, map[string]string{blockedPath(2): subs(9)})
	if next, ok, err := s.Next(); err != nil || ok {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
}

func TestAReviewAtTheTopIsTakenByAnyBox(t *testing.T) {
	t.Parallel()
	_, a, b := boxes(t)
	answers := map[string]string{
		// #2, labelled se-review, stands at the top; its only leaf has closed.
		listPath:    list(node(2, 1, ReviewLabel)),
		refsPath:    `[]`,
		subsPath(2): subs(-3),
	}
	gh := inTree(t, answers)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 2 || !next.Parent {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
	took, ok, err := s.Take(a, 0)
	if err != nil || !ok || took.Number != 2 {
		t.Fatalf("%+v %v %v", took, ok, err)
	}
	// The coordinator that claimed the tree has ended: another box picks the
	// tree up from its claim.
	seed(t, gh, map[string]string{refsPath: `[{"ref":"refs/heads/issue-2"}]`})
	if took, ok, err := s.Take(b, 2); err != nil || !ok || took.Number != 2 {
		t.Fatalf("%+v %v %v", took, ok, err)
	}
	if got := run(t, b, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-2" {
		t.Fatalf("b is on %s", got)
	}
	if tr, err := s.In(2); err != nil || !reflect.DeepEqual(numbers(tr.Review), []int{2}) || len(tr.Ready) != 0 {
		t.Fatalf("%+v %v", tr, err)
	}
}

func TestTakeInClaimsALeafForAWorktree(t *testing.T) {
	t.Parallel()
	origin, a, b := boxes(t)
	answers := map[string]string{
		listPath:    list(node(1, 2), node(2, 0), node(3, 0)),
		refsPath:    `[]`,
		subsPath(1): subs(2, 3),
	}
	gh := inTree(t, answers)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	if ok, err := (Source{Proc: machine}).claimTree(a, 1); err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	// Another box picks the tree up from its claim.
	if ok, err := (Source{Proc: machine}).claimTree(b, 1); err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	if got := run(t, b, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-1" {
		t.Fatalf("b is on %s", got)
	}
	took, ok, _, err := s.TakeIn(a, 1, 0)
	if err != nil || !ok || took.Number != 2 {
		t.Fatalf("%+v %v %v", took, ok, err)
	}
	if got := run(t, a, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-1" {
		t.Fatalf("a moved to %s", got)
	}
	if got, want := run(t, origin, "rev-parse", "issue-2"), run(t, origin, "rev-parse", "main"); got != want {
		t.Fatalf("issue-2 is %s", got)
	}
	run(t, a, "rev-parse", "origin/issue-2")
	// b read the same issues before a's claim showed: it moves to #3.
	if took, ok, _, err := s.TakeIn(b, 1, 2); err != nil || !ok || took.Number != 3 {
		t.Fatalf("%+v %v %v", took, ok, err)
	}
	shell(t, a, Worktree(a, 3))
	if got := run(t, WorktreeDir(a, 3), "rev-parse", "--abbrev-ref", "HEAD", "@{upstream}"); got != "issue-3\norigin/issue-3" {
		t.Fatalf("the worktree is on %s", got)
	}
	if _, _, _, err := s.TakeIn(a, 1, 9); err == nil || !strings.Contains(err.Error(), "not an open issue inside #1") {
		t.Fatalf("%v", err)
	}
}

func TestInSaysWhenTheRootHasClosed(t *testing.T) {
	t.Parallel()
	answers := map[string]string{
		listPath:    list(node(1, 1)),
		refsPath:    `[]`,
		subsPath(1): subs(-2),
	}
	gh := inTree(t, answers)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	if tr, err := s.In(1); err != nil || !tr.Closed {
		t.Fatalf("%+v %v", tr, err)
	}
	// Read again, it is closed already.
	if took, ok, tr, err := s.TakeIn(t.TempDir(), 1, 0); err != nil || ok || !tr.Closed {
		t.Fatalf("%+v %v %+v %v", took, ok, tr, err)
	}
	// Reopened by hand without its label, it is no fleet issue.
	seed(t, gh, map[string]string{"repos/o/r/issues/1": `{"number":1,"state":"open","labels":[]}`})
	if _, err := s.In(1); err == nil || !strings.Contains(err.Error(), "not an issue labelled se") {
		t.Fatalf("%v", err)
	}
}

// shell runs a command line as a box does, in dir.
func shell(t *testing.T, dir, line string) {
	t.Helper()
	cmd := exec.Command("sh", "-c", line)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%s: %v %s", line, err, out)
	}
}

func TestTheWorktreeCommandStartsFromTheNewestBranchAndMain(t *testing.T) {
	t.Parallel()
	origin, a, b := boxes(t)
	if ok, err := (Source{Proc: machine, Worktrees: true}).Claim(a, 4); err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	wt := WorktreeDir(a, 4)
	shell(t, a, Worktree(a, 4))
	// Another box pushes to issue-4 and to main while a's branch stands.
	run(t, b, "fetch", "-q", "origin")
	run(t, b, "checkout", "-q", "-b", "issue-4", "origin/issue-4")
	commitFile(t, b, "work", "b")
	run(t, b, "push", "-q", "origin", "issue-4")
	run(t, b, "checkout", "-q", "main")
	commitFile(t, b, "newer", "main")
	run(t, b, "push", "-q", "origin", "main")
	// a takes it over: its local branch and worktree are behind both.
	shell(t, a, Worktree(a, 4))
	for _, ref := range []string{run(t, origin, "rev-parse", "issue-4"), run(t, origin, "rev-parse", "main")} {
		run(t, wt, "merge-base", "--is-ancestor", ref, "HEAD")
	}
	if got := run(t, wt, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-4" {
		t.Fatalf("the worktree is on %s", got)
	}
	run(t, wt, "push", "-q", "origin", "issue-4")
	// A main that conflicts is left for the agent to merge: the branch stands as origin has it.
	run(t, b, "fetch", "-q", "origin")
	run(t, b, "checkout", "-q", "-B", "issue-4", "origin/issue-4")
	commitFile(t, b, "both", "branch")
	run(t, b, "push", "-q", "origin", "issue-4")
	run(t, b, "checkout", "-q", "-B", "main", "origin/main")
	commitFile(t, b, "both", "main")
	run(t, b, "push", "-q", "origin", "main")
	shell(t, a, Worktree(a, 4))
	if got, want := run(t, wt, "rev-parse", "HEAD"), run(t, origin, "rev-parse", "issue-4"); got != want {
		t.Fatalf("the worktree is at %s, not %s", got, want)
	}
	if got := run(t, wt, "status", "--porcelain"); got != "" {
		t.Fatalf("the worktree is not clean: %s", got)
	}
}

// held is an open issue for a person that hold minted, holding #n.
func held(h, n int) string {
	return fmt.Sprintf(`{"id":%d,"number":%d,"title":"Decide how #%d goes on","state":"open","html_url":"u%d","body":"Stuck.\n\n<!-- se:holds %d -->","labels":[{"name":"se"},{"name":"se-person"}]}`,
		1000+h, h, n, h, n)
}

// Recorded from mb-89/SE on 14 October: #134, for a person, held #95, and
// stayed open after #95 closed. An issue for a person whose held issue is
// closed closes by itself; one whose held issue is open, or one a person
// made by hand, stays.
func TestAHoldWhoseIssueClosedClosesItself(t *testing.T) {
	t.Parallel()
	gh := recorded(t, map[string]string{
		listPath:              list(node(5, 0), held(134, 95), held(135, 5), held(136, 96), node(137, 0, PersonLabel)),
		"repos/o/r/issues/95": `{"number":95,"state":"closed"}`,
		"repos/o/r/issues/96": `{"number":96,"state":"open"}`,
	})
	if err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}).CloseParents(); err != nil {
		t.Fatal(err)
	}
	want := []string{"POST repos/o/r/issues/134/comments", "PATCH repos/o/r/issues/134"}
	if w := gh.Writes(); !reflect.DeepEqual(w, want) {
		t.Fatalf("%q\nwant %q", w, want)
	}
	if i, c := issueAt(t, gh, 134), commentsAt(t, gh, 134); i.State != "closed" || len(c) != 1 || !strings.HasPrefix(c[0].Body, "#95, which this issue held, is closed") {
		t.Fatalf("#134: %+v %+v", i, c)
	}
	// hold marks the issue it mints with the issue it holds.
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	made, err := s.hold(Issue{Number: 5, Title: "t5", URL: "u5"}, "Stuck.")
	if err != nil {
		t.Fatal(err)
	}
	if got := issueAt(t, gh, made.Number); got.holds() != 5 {
		t.Fatalf("#%d holds %d: %q", made.Number, got.holds(), got.Body)
	}
}
