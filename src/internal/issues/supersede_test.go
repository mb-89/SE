// Internal test package: it reads the fake GitHub back through api.
package issues

import (
	"reflect"
	"slices"
	"strconv"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// superseding is GitHub as the box sees issue 5 it took: a sub-issue of 1,
// blocked by 3 (open) and 4 (closed), and blocking 7 (open) and 8 (closed).
func superseding(t *testing.T, labels string) *github.Fake {
	t.Helper()
	return recorded(t, map[string]string{
		"repos/o/r/issues/1":                         `{"id":101,"number":1,"state":"open","title":"Parent"}`,
		"repos/o/r/issues/3":                         `{"id":303,"number":3,"state":"open"}`,
		"repos/o/r/issues/4":                         `{"id":404,"number":4,"state":"closed"}`,
		"repos/o/r/issues/5":                         `{"id":505,"number":5,"state":"open","title":"Do it","body":"The task.\n\n<!-- se:new -->","labels":[` + labels + `]}`,
		"repos/o/r/issues/7":                         `{"id":707,"number":7,"state":"open"}`,
		"repos/o/r/issues/8":                         `{"id":808,"number":8,"state":"closed"}`,
		"repos/o/r/issues/1/sub_issues?per_page=100": `[{"number":5}]`,
		"repos/o/r/issues/5/dependencies/blocked_by?per_page=100": `[{"number":3},{"number":4}]`,
		"repos/o/r/issues/5/dependencies/blocking?per_page=100":   `[{"number":7},{"number":8}]`,
	})
}

func TestSupersedeHandsTheIssueOnToAFinalSuccessor(t *testing.T) {
	t.Parallel()
	gh := superseding(t, `{"name":"se"}`)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	sup, err := s.Supersede(5, "Which API?\n")
	if err != nil {
		t.Fatal(err)
	}
	m := sup.Successor.Number
	if m == 0 || sup.Parent != 1 || !reflect.DeepEqual(sup.BlockedBy, []int{3}) || !reflect.DeepEqual(sup.Blocks, []int{7}) || sup.Ready {
		t.Fatalf("%+v", sup)
	}
	next := issueAt(t, gh, m)
	want := "Supersedes #5, whose box could not close it with a PR. This is its last attempt (se-final): its box lands a PR.\n\nThe task.\n\n## Open questions\nWhich API?\n\n<!-- se:new -->"
	if next.Title != "Do it" || next.Body != want || !next.labelled(Label) || !next.labelled(FinalLabel) {
		t.Fatalf("%+v", next)
	}
	if p, err := s.parentOf(m); err != nil || p != 1 {
		t.Fatalf("parent %d %v", p, err)
	}
	if got := linksOf(t, gh, "repos/o/r/issues/"+strconv.Itoa(m)+"/dependencies/blocked_by"); !reflect.DeepEqual(got, []int{3}) {
		t.Fatalf("the successor is blocked by %v", got)
	}
	// The superseded issue's dependents wait on the successor.
	if got := linksOf(t, gh, "repos/o/r/issues/7/dependencies/blocked_by"); !slices.Contains(got, m) {
		t.Fatalf("#7 is blocked by %v", got)
	}
	old := issueAt(t, gh, 5)
	if old.State != "closed" || old.StateReason != "not_planned" {
		t.Fatalf("%+v", old)
	}
	if cs := commentsAt(t, gh, 5); len(cs) != 1 || !strings.HasPrefix(cs[0].Body, "Superseded by #"+strconv.Itoa(m)+",") {
		t.Fatalf("%+v", cs)
	}
}

func TestSupersedeRefusesAFinalIssue(t *testing.T) {
	t.Parallel()
	gh := superseding(t, `{"name":"se"},{"name":"se-final"}`)
	_, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Supersede(5, "Which API?")
	if err == nil || !strings.Contains(err.Error(), "#5 is final") {
		t.Fatalf("%v", err)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("wrote %q", w)
	}
}

func TestSupersedeRefusesNoQuestionsAndAClosedIssue(t *testing.T) {
	t.Parallel()
	s := Source{Proc: machine, Repo: repo, GitHub: superseding(t, `{"name":"se"}`), Clock: atNow()}
	if _, err := s.Supersede(5, " \n"); err == nil || !strings.Contains(err.Error(), "open questions") {
		t.Fatalf("%v", err)
	}
	if _, err := s.Supersede(4, "Which API?"); err == nil || !strings.Contains(err.Error(), "closed already") {
		t.Fatalf("%v", err)
	}
	if _, err := s.Supersede(99, "Which API?"); err == nil || !strings.Contains(err.Error(), "#99 does not exist") {
		t.Fatalf("%v", err)
	}
}

func TestUnclosedNamesWhatIsMissing(t *testing.T) {
	t.Parallel()
	pulls := "repos/o/r/pulls?head=o:issue-5&base=main&state=open&per_page=100"
	at := func(more map[string]string) Source {
		a := map[string]string{"repos/o/r/issues/5": `{"number":5,"state":"open"}`}
		for k, v := range more {
			a[k] = v
		}
		return Source{Proc: machine, Repo: repo, GitHub: recorded(t, a), Clock: atNow()}
	}
	if why, err := at(nil).Unclosed(5); err != nil || !strings.Contains(why, "neither a PR from issue-5 nor a supersede") {
		t.Fatalf("%q %v", why, err)
	}
	s := at(map[string]string{pulls: `[{"number":9,"html_url":"p9","auto_merge":null}]`})
	if why, err := s.Unclosed(5); err != nil || !strings.Contains(why, "PR #9 (p9) has auto-merge off") {
		t.Fatalf("%q %v", why, err)
	}
	// A box keeps its PR until it merges: auto-merge on is not yet done.
	s = at(map[string]string{pulls: `[{"number":9,"html_url":"p9","auto_merge":{"merge_method":"squash"}}]`})
	if why, err := s.Unclosed(5); err != nil || !strings.Contains(why, "PR #9 (p9) has not merged") || !strings.Contains(why, "se issue keep") {
		t.Fatalf("%q %v", why, err)
	}
	// Taken over by another box, it is that box's to keep.
	s = at(map[string]string{
		pulls:                         `[{"number":9,"html_url":"p9","auto_merge":{"merge_method":"squash"}}]`,
		"repos/o/r/issues/5/comments": `[{"id":1,"body":"Claimed.\n<!-- se:box s1 -->"},{"id":2,"body":"Took over.\n<!-- se:box s2 -->"}]`,
	})
	s.Box = "s1"
	if why, err := s.Unclosed(5); err != nil || why != "" {
		t.Fatalf("%q %v", why, err)
	}
	s.Box = "s2"
	if why, err := s.Unclosed(5); err != nil || !strings.Contains(why, "has not merged") {
		t.Fatalf("%q %v", why, err)
	}
	// Superseded, or merged: closed.
	s = at(map[string]string{"repos/o/r/issues/5": `{"number":5,"state":"closed"}`})
	if why, err := s.Unclosed(5); err != nil || why != "" {
		t.Fatalf("%q %v", why, err)
	}
	// What GitHub does not answer is an error, never a pass.
	if _, err := s.Unclosed(6); err == nil {
		t.Fatal("answered without GitHub")
	}
}

func TestDuplicateClosesTheIssueAndMintsNothing(t *testing.T) {
	t.Parallel()
	// Issue 5 is final: a duplicate closes it all the same.
	gh := superseding(t, `{"name":"se"},{"name":"se-final"}`)
	seed(t, gh, map[string]string{
		"repos/o/r/issues/6": `{"id":606,"number":6,"state":"open","title":"The same","html_url":"u6"}`,
		"repos/o/r/issues/6/dependencies/blocking?per_page=100": `[]`,
	})
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	dup, err := s.CloseDuplicate(5, 6)
	if err != nil {
		t.Fatal(err)
	}
	if dup.Issue != 5 || dup.Of != 6 || dup.URL != "u6" || !reflect.DeepEqual(dup.Blocks, []int{7}) {
		t.Fatalf("%+v", dup)
	}
	old := issueAt(t, gh, 5)
	if old.State != "closed" || old.StateReason != "duplicate" {
		t.Fatalf("%+v", old)
	}
	if cs := commentsAt(t, gh, 5); len(cs) != 1 || !strings.HasPrefix(cs[0].Body, "Duplicate of #6,") {
		t.Fatalf("%+v", cs)
	}
	// What waited on the duplicate waits on the issue that covers it.
	if got := linksOf(t, gh, "repos/o/r/issues/7/dependencies/blocked_by"); !slices.Contains(got, 6) {
		t.Fatalf("#7 is blocked by %v", got)
	}
	for _, w := range gh.Writes() {
		if strings.HasPrefix(w, "POST repos/o/r/issues ") || w == "POST repos/o/r/issues" {
			t.Fatalf("minted an issue: %q", gh.Writes())
		}
	}
}

func TestDuplicateRefusesAClosedOrMissingIssue(t *testing.T) {
	t.Parallel()
	gh := superseding(t, `{"name":"se"}`)
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	for _, c := range []struct {
		n, of int
		want  string
	}{
		{5, 5, "cannot duplicate itself"},
		{5, 4, "#4 is closed"},
		{4, 3, "#4 is closed already"},
		{5, 99, "#99 does not exist"},
	} {
		if _, err := s.CloseDuplicate(c.n, c.of); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Fatalf("%d of %d: %v", c.n, c.of, err)
		}
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("wrote %q", w)
	}
}

func TestDuplicateRefusesAnOpenPullRequest(t *testing.T) {
	t.Parallel()
	// #356 closed as a duplicate of the open PR #364, which had not merged:
	// an issue duplicates an open issue or a merged PR, never an open PR.
	gh := superseding(t, `{"name":"se"}`)
	seed(t, gh, map[string]string{
		"repos/o/r/issues/9":  `{"id":909,"number":9,"state":"open","pull_request":{}}`,
		"repos/o/r/pulls/9":   `{"number":9,"state":"open","merged":false}`,
		"repos/o/r/issues/10": `{"id":1010,"number":10,"state":"closed","pull_request":{}}`,
		"repos/o/r/pulls/10":  `{"number":10,"state":"closed","merged":false}`,
	})
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	for of, want := range map[int]string{9: "#9 is an open pull request", 10: "closed unmerged"} {
		if _, err := s.CloseDuplicate(5, of); err == nil || !strings.Contains(err.Error(), want) {
			t.Fatalf("of %d: %v", of, err)
		}
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("wrote %q", w)
	}
	if old := issueAt(t, gh, 5); old.State != "open" {
		t.Fatalf("%+v", old)
	}
}

func TestDuplicateOfAMergedPullRequestNamesItsCommit(t *testing.T) {
	t.Parallel()
	gh := superseding(t, `{"name":"se"}`)
	sha := "0123456789abcdef0123456789abcdef01234567"
	seed(t, gh, map[string]string{
		"repos/o/r/issues/9": `{"id":909,"number":9,"state":"closed","pull_request":{}}`,
		"repos/o/r/pulls/9":  `{"number":9,"state":"closed","merged":true,"merge_commit_sha":"` + sha + `","title":"The fix"}`,
	})
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	dup, err := s.CloseDuplicate(5, 9)
	if err != nil {
		t.Fatal(err)
	}
	if dup.Of != 9 || dup.Commit != sha || dup.URL != "https://github.com/o/r/commit/"+sha || len(dup.Blocks) != 0 {
		t.Fatalf("%+v", dup)
	}
	if old := issueAt(t, gh, 5); old.State != "closed" || old.StateReason != "duplicate" {
		t.Fatalf("%+v", old)
	}
	cs := commentsAt(t, gh, 5)
	if len(cs) != 1 || !strings.Contains(cs[0].Body, "<!-- se:fixed-by "+sha+" -->") || !strings.Contains(cs[0].Body, "Duplicate of PR #9, merged") {
		t.Fatalf("%+v", cs)
	}
}
