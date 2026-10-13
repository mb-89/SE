package issues

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
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

// inTree answers like recorded, and an issue's links it holds no answer for
// as none, since every unclaimed issue's links are asked for.
func inTree(t *testing.T, answers map[string]string) GH {
	t.Helper()
	gh := recorded(t, answers)
	return func(args ...string) ([]byte, error) {
		path := args[len(args)-1]
		if _, ok := answers[path]; !ok && strings.HasSuffix(path, "/dependencies/blocked_by?per_page=100") {
			return []byte(`[]`), nil
		}
		return gh(args...)
	}
}

func subsPath(n int) string { return fmt.Sprintf("repos/o/r/issues/%d/sub_issues?per_page=100", n) }

func blockedPath(n int) string {
	return fmt.Sprintf("repos/o/r/issues/%d/dependencies/blocked_by?per_page=100", n)
}

func list(nodes ...string) string { return "[" + strings.Join(nodes, ",") + "]" }

func TestASubIssueIsNeverOfferedAtTheTop(t *testing.T) {
	answers := map[string]string{
		// #1 is a parent of #2 and #3; #4 stands alone.
		listPath:    list(node(3, 0), node(2, 0), node(1, 2), node(4, 0)),
		refsPath:    `[]`,
		subsPath(1): subs(2, 3),
	}
	s := Source{Repo: repo, GH: inTree(t, answers)}
	next, ok, err := s.Next()
	if err != nil || !ok || next.Number != 1 || !next.Parent {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
	if _, _, err := s.Take(t.TempDir(), 2); err == nil || !strings.Contains(err.Error(), "#2 is a sub-issue of #1") {
		t.Fatalf("%v", err)
	}
	// With the parent blocked, its sub-issues are still not offered.
	answers[listPath] = list(node(3, 0), node(2, 0), node(1, 2), node(4, 0))
	answers[blockedPath(1)] = subs(9)
	next, ok, err = s.Next()
	if err != nil || !ok || next.Number != 4 || next.Parent {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
	// Nor with every leaf at the top claimed.
	answers[refsPath] = `[{"ref":"refs/heads/issue-4"}]`
	if next, ok, err := s.Next(); err != nil || ok {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
}

func TestInOffersTheReadyLeavesAtAnyDepth(t *testing.T) {
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
	}
	s := Source{Repo: repo, GH: inTree(t, answers)}
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
	gh, calls := writes(t, map[string]string{
		// #1 holds #2 and a closed #3; #2 holds only closed sub-issues, so
		// once #2 closes, #1 does too. #6 still has an open sub-issue.
		listPath:                      list(node(1, 2), node(2, 2), node(6, 2), node(7, 0)),
		subsPath(1):                   subs(2, -3),
		subsPath(2):                   subs(-4, -5),
		subsPath(6):                   subs(7, -8),
		"repos/o/r/issues/1/comments": `{}`,
		"repos/o/r/issues/1":          `{}`,
		"repos/o/r/issues/2/comments": `{}`,
		"repos/o/r/issues/2":          `{}`,
	})
	if err := (Source{Repo: repo, GH: gh}).CloseParents(); err != nil {
		t.Fatal(err)
	}
	var wrote [][]string
	for _, c := range *calls {
		if c[1] == "-X" {
			wrote = append(wrote, c)
		}
	}
	want := [][]string{
		{"api", "-X", "POST", "-f", "body=All sub-issues of #2 are closed, so it closes by itself.", "repos/o/r/issues/2/comments"},
		{"api", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=completed", "repos/o/r/issues/2"},
		{"api", "-X", "POST", "-f", "body=All sub-issues of #1 are closed, so it closes by itself.", "repos/o/r/issues/1/comments"},
		{"api", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=completed", "repos/o/r/issues/1"},
	}
	if !reflect.DeepEqual(wrote, want) {
		t.Fatalf("%q\nwant %q", wrote, want)
	}
}

func TestAReviewParentNeverClosesByItself(t *testing.T) {
	answers := map[string]string{
		// #1 is the root; #2, labelled se-review, has only closed sub-issues;
		// #5 waits on #2.
		listPath:       list(node(1, 2), node(2, 2, ReviewLabel), node(5, 0)),
		refsPath:       `[]`,
		subsPath(1):    subs(2, 5),
		subsPath(2):    subs(-3, -4),
		blockedPath(5): subs(2),
	}
	s := Source{Repo: repo, GH: inTree(t, answers)} // a write would not be recorded
	tr, err := s.In(1)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(numbers(tr.Review), []int{2}) || len(tr.Ready) != 0 || tr.Closed {
		t.Fatalf("%+v", tr)
	}
	// Nothing is work, so the root is not offered, and the review is not taken.
	if next, ok, err := s.Next(); err != nil || ok {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
	if _, _, _, err := s.TakeIn(t.TempDir(), 1, 2); err == nil || !strings.Contains(err.Error(), "a parent holds no work") {
		t.Fatalf("%v", err)
	}
	// At the top, too, it waits for its review.
	answers[listPath] = list(node(2, 2, ReviewLabel))
	if tr, err := s.In(2); err != nil || !reflect.DeepEqual(numbers(tr.Review), []int{2}) {
		t.Fatalf("%+v %v", tr, err)
	}
	if _, _, err := s.Take(t.TempDir(), 2); err == nil || !strings.Contains(err.Error(), "waits for its review") {
		t.Fatalf("%v", err)
	}
}

func TestTakeInClaimsALeafForAWorktree(t *testing.T) {
	origin, a, b := boxes(t)
	answers := map[string]string{
		listPath:    list(node(1, 2), node(2, 0), node(3, 0)),
		refsPath:    `[]`,
		subsPath(1): subs(2, 3),
	}
	s := Source{Repo: repo, GH: inTree(t, answers)}
	if ok, err := claimTree(a, 1); err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	// Another box picks the tree up from its claim.
	if ok, err := claimTree(b, 1); err != nil || !ok {
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
	cmd := Worktree(a, 3)
	if !strings.HasPrefix(cmd, "git worktree add --track -b issue-3 ") || !strings.HasSuffix(cmd, " origin/issue-3") {
		t.Fatal(cmd)
	}
	run(t, a, "fetch", "-q", "origin", "issue-3:refs/remotes/origin/issue-3")
	run(t, a, strings.Fields(cmd)[1:]...)
	if _, _, _, err := s.TakeIn(a, 1, 9); err == nil || !strings.Contains(err.Error(), "not an open issue inside #1") {
		t.Fatalf("%v", err)
	}
}

func TestInSaysWhenTheRootHasClosed(t *testing.T) {
	answers := map[string]string{
		listPath:                      list(node(1, 1)),
		refsPath:                      `[]`,
		subsPath(1):                   subs(-2),
		"repos/o/r/issues/1/comments": `{}`,
		"repos/o/r/issues/1":          `{}`,
	}
	s := Source{Repo: repo, GH: inTree(t, answers)}
	if tr, err := s.In(1); err != nil || !tr.Closed {
		t.Fatalf("%+v %v", tr, err)
	}
	// Read again, it is closed already.
	answers[listPath] = `[]`
	answers["repos/o/r/issues/1"] = `{"number":1,"state":"closed"}`
	if took, ok, tr, err := s.TakeIn(t.TempDir(), 1, 0); err != nil || ok || !tr.Closed {
		t.Fatalf("%+v %v %+v %v", took, ok, tr, err)
	}
	answers["repos/o/r/issues/1"] = `{"number":1,"state":"open"}`
	if _, err := s.In(1); err == nil || !strings.Contains(err.Error(), "not an issue labelled se") {
		t.Fatalf("%v", err)
	}
}
