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
	s = at(map[string]string{pulls: `[{"number":9,"html_url":"p9","auto_merge":{"merge_method":"squash"}}]`})
	if why, err := s.Unclosed(5); err != nil || why != "" {
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
