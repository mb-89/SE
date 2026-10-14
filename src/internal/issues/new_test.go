// Internal test package: its fake GitHub serves the package's other internal tests.
package issues

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/modules/io/github"
)

func TestBlockedByIsANumberListOrNone(t *testing.T) {
	t.Parallel()
	for in, want := range map[string][]int{"none": nil, "5": {5}, "5,8": {5, 8}, " #8, 5 ,8": {5, 8}} {
		if got, err := ParseBlockedBy(in); err != nil || !reflect.DeepEqual(got, want) {
			t.Errorf("%q: %v %v, want %v", in, got, err, want)
		}
	}
	for _, in := range []string{"", " ", "5,", "x", "0", "-1", "None", "5;8"} {
		if got, err := ParseBlockedBy(in); err == nil {
			t.Errorf("%q: %v, want refused", in, got)
		}
	}
}

// linksOf reads the numbers of the issues a links path lists.
func linksOf(t *testing.T, gh *github.Fake, path string) []int {
	t.Helper()
	out, err := gh.List(path)
	if err != nil {
		t.Fatal(err)
	}
	var is []issue
	if err := json.Unmarshal(out, &is); err != nil {
		t.Fatal(err)
	}
	ns := []int{}
	for _, i := range is {
		ns = append(ns, i.Number)
	}
	return ns
}

func TestBlockWritesNativeLinksByIssueID(t *testing.T) {
	t.Parallel()
	gh := recorded(t, map[string]string{
		"repos/o/r/issues/8": `{"id":808,"number":8,"state":"open"}`,
		"repos/o/r/issues/6": `{"id":606,"number":6,"state":"open"}`,
	})
	if err := (Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}).Block(6, []int{8}); err != nil {
		t.Fatal(err)
	}
	if w := gh.Writes(); !reflect.DeepEqual(w, []string{"POST repos/o/r/issues/6/dependencies/blocked_by"}) {
		t.Fatalf("%q", w)
	}
	if got := linksOf(t, gh, "repos/o/r/issues/6/dependencies/blocked_by"); !reflect.DeepEqual(got, []int{8}) {
		t.Fatalf("#6 is blocked by %v", got)
	}
}

func TestBlockRefusesAMissingBlockerBeforeWriting(t *testing.T) {
	t.Parallel()
	gh := recorded(t, map[string]string{"repos/o/r/issues/8": `{"id":808,"number":8}`, "repos/o/r/issues/6": `{"id":606,"number":6}`})
	err := (Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}).Block(6, []int{8, 99})
	if err == nil || !strings.Contains(err.Error(), "#99 does not exist") {
		t.Fatalf("%v", err)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("wrote %q", w)
	}
	if err := (Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}).Block(8, []int{8}); err == nil || !strings.Contains(err.Error(), "block itself") {
		t.Fatalf("%v", err)
	}
}

func TestCreateNamesTheIssueWhoseLinkFailed(t *testing.T) {
	t.Parallel()
	// #8 is a pull request on GitHub's side by the time the link is written:
	// the link is refused, and the error names the issue already created.
	gh := recorded(t, map[string]string{
		"repos/o/r/issues/8":  `{"id":808,"number":8}`,
		"repos/o/r/issues/10": `{"id":1010,"number":10}`,
	})
	s := Source{Git: machine, Repo: repo, GitHub: refuseLinks{gh}, Clock: atNow()}
	made, _, err := s.Create("t", "b", 10, []int{8})
	if made.Number != 11 || err == nil || !strings.Contains(err.Error(), "created #11 (https://github.com/o/r/issues/11), but linking #11 as blocked by #8") {
		t.Fatalf("%+v %v", made, err)
	}
}

// refuseLinks is GitHub where the token may not write links.
type refuseLinks struct{ github.GitHub }

func (r refuseLinks) Send(method, path string, fields ...github.Field) ([]byte, error) {
	if strings.HasSuffix(path, "/dependencies/blocked_by") {
		return nil, &github.Error{Status: 403, Message: "gh: Resource not accessible by integration"}
	}
	return r.GitHub.Send(method, path, fields...)
}

func TestCreateMakesASubIssueOfItsParent(t *testing.T) {
	t.Parallel()
	gh := recorded(t, map[string]string{"repos/o/r/issues/1": `{"id":101,"number":1,"state":"open"}`})
	made, _, err := (Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}).Create("t", "b", 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"POST repos/o/r/issues", "POST repos/o/r/issues/1/sub_issues"}
	if w := gh.Writes(); !reflect.DeepEqual(w, want) {
		t.Fatalf("%q", w)
	}
	if got := linksOf(t, gh, "repos/o/r/issues/1/sub_issues"); !reflect.DeepEqual(got, []int{made.Number}) {
		t.Fatalf("#1's sub-issues are %v", got)
	}
	out, err := gh.Get(fmt.Sprintf("repos/o/r/issues/%d", made.Number))
	if err != nil || !strings.Contains(string(out), `"body":"b\n\n<!-- se:new -->"`) || !strings.Contains(string(out), `"labels":[{"name":"se"}]`) {
		t.Fatalf("%s %v", out, err)
	}
	// A parent that does not exist creates nothing.
	if _, _, err := (Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}).Create("t", "b", 9, nil); err == nil || !strings.Contains(err.Error(), "#9 does not exist") {
		t.Fatalf("%v", err)
	}
	if w := gh.Writes(); len(w) != 2 {
		t.Fatalf("wrote %q", w)
	}
}

func TestDuplicateIsAnOpenIssueOfTheSameTitleUnderTheSameParent(t *testing.T) {
	t.Parallel()
	gh := recorded(t, map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100": `[
			{"number":1,"title":"root","state":"open","sub_issues_summary":{"total":2}},
			{"number":2,"title":"leaf","state":"open"},
			{"number":3,"title":"leaf ","state":"open"}]`,
		"repos/o/r/issues/1/sub_issues?per_page=100": `[{"number":3,"state":"open"},{"number":4,"title":"done","state":"closed"}]`,
	})
	s := Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	for _, c := range []struct {
		title  string
		parent int
		want   int
	}{{"leaf", 0, 2}, {" leaf", 1, 3}, {"root", 0, 1}, {"root", 1, 0}, {"done", 1, 0}, {"Leaf", 0, 0}} {
		if got, err := s.Duplicate(c.title, c.parent); err != nil || got != c.want {
			t.Errorf("%q under #%d: %d %v, want %d", c.title, c.parent, got, err, c.want)
		}
	}
}
