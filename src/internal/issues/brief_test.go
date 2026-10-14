// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"encoding/base64"
	"fmt"
	"reflect"
	"strings"
	"sync"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// briefAnswers is gate #1 holding #2, a parent of #3, and #5; main is at
// abc. #3 landed as PR #30, whose description and landing answers are the
// worker's own account.
func briefAnswers() map[string]string {
	return map[string]string{
		"repos/o/r/issues/1": `{"number":1,"title":"the gate","body":"Is it sound?","state":"open"}`,
		subsPath(1): `[{"number":2,"title":"part","body":"ask 2","state":"closed","state_reason":"completed","sub_issues_summary":{"total":1}},` +
			`{"number":5,"title":"dropped","body":"ask 5","state":"closed","state_reason":"not_planned"}]`,
		subsPath(2):              `[{"number":3,"title":"leaf","body":"ask 3: it must hold","state":"closed","state_reason":"completed"}]`,
		"repos/o/r/commits/main": `{"sha":"abc"}`,
		"repos/o/r/commits/abc/check-runs?per_page=100": `{"check_runs":[{"name":"check","status":"completed","conclusion":"success"}]}`,
		"repos/o/r/contents/spec/principles.md?ref=abc": fmt.Sprintf(`{"content":%q,"encoding":"base64"}`, base64.StdEncoding.EncodeToString([]byte("1. Locality.\n"))),
		commentsPath(1): `[]`,
		// What --claims reads, and only it.
		"repos/o/r/pulls?state=closed&base=main&per_page=100": `[{"number":30,"html_url":"p30","body":"Fixes #3. This is bug-free.","merged_at":"2026-10-12T00:00:00Z","head":{"ref":"issue-3"}},` +
			`{"number":31,"body":"never merged","merged_at":null,"head":{"ref":"issue-5"}}]`,
		commentsPath(3): `[{"body":"<!-- se:landing -->\nLanding answers: all tested."},{"body":"Worked by session s in /w.\n\n<!-- se-worker {\"session\":\"s\",\"workspace\":\"/w\"} -->"}]`,
		commentsPath(5): `[]`,
	}
}

// reads is a GitHub that keeps the paths it was asked to read, one at a
// time, as reads run in parallel.
type reads struct {
	github.GitHub
	mu    *sync.Mutex
	paths *[]string
}

func (r reads) note(path string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	*r.paths = append(*r.paths, path)
}

func (r reads) Get(path string) ([]byte, error) {
	r.note(path)
	return r.GitHub.Get(path)
}

func (r reads) List(path string) ([]byte, error) {
	r.note(path)
	return r.GitHub.List(path)
}

// asked records the paths a brief reads.
func asked(t *testing.T, answers map[string]string) (github.GitHub, *[]string) {
	var paths []string
	return reads{recorded(t, answers), &sync.Mutex{}, &paths}, &paths
}

func TestTheBriefWithholdsTheWorkersAccounts(t *testing.T) {
	t.Parallel()
	gh, paths := asked(t, briefAnswers())
	b, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Brief(1, false)
	if err != nil {
		t.Fatal(err)
	}
	if b.Commit != "abc" || b.Principles != "1. Locality.\n" || len(b.CI) != 1 || b.CI[0].Conclusion != "success" || b.Rereview != nil || b.Claims != nil {
		t.Fatalf("%+v", b)
	}
	var tree []string
	for _, i := range b.Tree {
		tree = append(tree, fmt.Sprintf("%d<%d %s", i.Number, i.Above, i.Body))
	}
	if want := []string{"2<1 ask 2", "3<2 ask 3: it must hold", "5<1 ask 5"}; !reflect.DeepEqual(tree, want) {
		t.Fatalf("tree %q", tree)
	}
	// No PR is read, nor a leaf's comments, and nothing of them is shown.
	for _, p := range *paths {
		if strings.Contains(p, "pulls") || p == commentsPath(3) {
			t.Errorf("the brief read %s", p)
		}
	}
	text := b.Text()
	for _, want := range []string{
		"git checkout --detach abc", "## The question: #1 the gate (open)\n\n> Is it sound?", "### #3 leaf (closed, completed, under #2)\n\n> ask 3: it must hold",
		"- check: completed success", "1. Locality.", "## Withheld",
	} {
		if !strings.Contains(text, want) {
			t.Errorf("the brief lacks %q:\n%s", want, text)
		}
	}
	for _, never := range []string{"bug-free", "Landing answers", "re-review"} {
		if strings.Contains(text, never) {
			t.Errorf("the brief shows %q:\n%s", never, text)
		}
	}

	// Once the findings are verified, --claims shows them, as claims.
	gh, _ = asked(t, briefAnswers())
	b, err = Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Brief(1, true)
	if err != nil {
		t.Fatal(err)
	}
	if want := []Account{{Issue: 3, PR: 30, URL: "p30", Body: "Fixes #3. This is bug-free.", Comments: []string{"Landing answers: all tested.", "Worked by session s in /w."}}, {Issue: 5}}; !reflect.DeepEqual(b.Claims, want) {
		t.Fatalf("claims %+v", b.Claims)
	}
	if text := b.Text(); !strings.Contains(text, "## Claims to check, never evidence") || !strings.Contains(text, "PR #30 p30 says:\n\n> Fixes #3. This is bug-free.") {
		t.Fatal(text)
	}
}

func TestTheBriefOfAReReviewNamesTheEarlierBlockersAndTheDiff(t *testing.T) {
	t.Parallel()
	answers := briefAnswers()
	earlier := Verdict{Report: failing("three")}
	earlier.Report.Findings[0].Issue = 3
	answers[commentsPath(1)] = fmt.Sprintf(`[{"body":%q}]`, earlier.render(Worker{Session: "r", Workspace: "/r"}))
	// Without a principles file, the brief says so.
	delete(answers, "repos/o/r/contents/spec/principles.md?ref=abc")
	s := Source{Proc: machine, Repo: repo, GitHub: recorded(t, answers), Clock: atNow()}
	b, err := s.Brief(1, false)
	if err != nil {
		t.Fatal(err)
	}
	if want := (&Rereview{Since: "c0ffee", Blockers: []int{3}, Diff: "git diff c0ffee..abc"}); !reflect.DeepEqual(b.Rereview, want) {
		t.Fatalf("%+v", b.Rereview)
	}
	text := b.Text()
	for _, want := range []string{"This is a re-review", "earlier blockers, #3", "`git diff c0ffee..abc`", "There is no spec/principles.md at abc"} {
		if !strings.Contains(text, want) {
			t.Errorf("the brief lacks %q:\n%s", want, text)
		}
	}
}
