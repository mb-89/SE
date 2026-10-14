// Internal test package: it shares the fake GitHub of new_test.go.
package issues

import (
	"reflect"
	"strings"
	"testing"
)

// superseding is GitHub as the box sees issue 5 it took: a sub-issue of 1,
// blocked by 3 (open) and 4 (closed), and blocking 7.
func superseding(labels string) map[string]string {
	return map[string]string{
		"repos/o/r/issues/5":                                      `{"id":505,"number":5,"state":"open","title":"Do it","body":"The task.\n\n<!-- se:new -->","labels":[` + labels + `]}`,
		"repos/o/r/issues/5/parent":                               `{"id":101,"number":1}`,
		"repos/o/r/issues/5/dependencies/blocked_by?per_page=100": `[{"number":3,"state":"open"},{"number":4,"state":"closed"}]`,
		"repos/o/r/issues/5/dependencies/blocking?per_page=100":   `[{"number":7,"state":"open"},{"number":8,"state":"closed"}]`,
		"repos/o/r/issues/1":                                      `{"id":101,"number":1,"state":"open"}`,
		"repos/o/r/issues/3":                                      `{"id":303,"number":3,"state":"open"}`,
		"repos/o/r/issues":                                        `{"id":1200,"number":12,"title":"Do it","html_url":"u12"}`,
		"repos/o/r/issues/1/sub_issues":                           `{}`,
		"repos/o/r/issues/12/dependencies/blocked_by":             `{}`,
		"repos/o/r/issues/7/dependencies/blocked_by":              `{}`,
		"repos/o/r/issues/5/comments":                             `{}`,
	}
}

func TestSupersedeHandsTheIssueOnToAFinalSuccessor(t *testing.T) {
	gh, calls := writes(t, superseding(`{"name":"se"}`))
	sup, err := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}.Supersede(5, "Which API?\n")
	if err != nil {
		t.Fatal(err)
	}
	if sup.Successor.Number != 12 || sup.Parent != 1 || !reflect.DeepEqual(sup.BlockedBy, []int{3}) || !reflect.DeepEqual(sup.Blocks, []int{7}) || sup.Ready {
		t.Fatalf("%+v", sup)
	}
	var writes [][]string
	for _, c := range *calls {
		if c[1] == "-X" {
			writes = append(writes, c)
		}
	}
	body := "body=Supersedes #5, whose box could not close it with a PR. This is its last attempt (se-final): its box lands a PR.\n\nThe task.\n\n## Open questions\nWhich API?\n\n<!-- se:new -->"
	want := [][]string{
		{"api", "-X", "POST", "-f", "title=Do it", "-f", body, "-f", "labels[]=se", "-f", "labels[]=se-final", "repos/o/r/issues"},
		{"api", "-X", "POST", "-F", "sub_issue_id=1200", "repos/o/r/issues/1/sub_issues"},
		{"api", "-X", "POST", "-F", "issue_id=303", "repos/o/r/issues/12/dependencies/blocked_by"},
		// The superseded issue's dependents wait on the successor.
		{"api", "-X", "POST", "-F", "issue_id=1200", "repos/o/r/issues/7/dependencies/blocked_by"},
		{"api", "-X", "POST", "-f", "body=Superseded by #12, which carries this issue on with the questions its box could not answer.\nu12", "repos/o/r/issues/5/comments"},
		{"api", "-X", "PATCH", "-f", "state=closed", "-f", "state_reason=not_planned", "repos/o/r/issues/5"},
	}
	if !reflect.DeepEqual(writes, want) {
		t.Fatalf("%q", writes)
	}
}

func TestSupersedeRefusesAFinalIssue(t *testing.T) {
	gh, calls := writes(t, superseding(`{"name":"se"},{"name":"se-final"}`))
	_, err := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}.Supersede(5, "Which API?")
	if err == nil || !strings.Contains(err.Error(), "#5 is final") {
		t.Fatalf("%v", err)
	}
	for _, c := range *calls {
		if c[1] == "-X" {
			t.Fatalf("wrote %v", c)
		}
	}
}

func TestSupersedeRefusesNoQuestionsAndAClosedIssue(t *testing.T) {
	a := superseding(`{"name":"se"}`)
	gh, _ := writes(t, a)
	s := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}
	if _, err := s.Supersede(5, " \n"); err == nil || !strings.Contains(err.Error(), "open questions") {
		t.Fatalf("%v", err)
	}
	a["repos/o/r/issues/5"] = `{"id":505,"number":5,"state":"closed"}`
	if _, err := s.Supersede(5, "Which API?"); err == nil || !strings.Contains(err.Error(), "closed already") {
		t.Fatalf("%v", err)
	}
}

func TestUnclosedNamesWhatIsMissing(t *testing.T) {
	a := map[string]string{"repos/o/r/issues/5": `{"number":5,"state":"open"}`}
	pulls := "repos/o/r/pulls?head=o:issue-5&base=main&state=open&per_page=100"
	gh, _ := writes(t, a)
	s := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}
	a[pulls] = `[]`
	if why, err := s.Unclosed(5); err != nil || !strings.Contains(why, "neither a PR from issue-5 nor a supersede") {
		t.Fatalf("%q %v", why, err)
	}
	a[pulls] = `[{"number":9,"html_url":"p9","auto_merge":null}]`
	if why, err := s.Unclosed(5); err != nil || !strings.Contains(why, "PR #9 (p9) has auto-merge off") {
		t.Fatalf("%q %v", why, err)
	}
	a[pulls] = `[{"number":9,"html_url":"p9","auto_merge":{"merge_method":"squash"}}]`
	if why, err := s.Unclosed(5); err != nil || why != "" {
		t.Fatalf("%q %v", why, err)
	}
	// Superseded, or merged: closed.
	a[pulls] = `[]`
	a["repos/o/r/issues/5"] = `{"number":5,"state":"closed"}`
	if why, err := s.Unclosed(5); err != nil || why != "" {
		t.Fatalf("%q %v", why, err)
	}
	// What GitHub does not answer is an error, never a pass.
	delete(a, "repos/o/r/issues/5")
	if _, err := s.Unclosed(5); err == nil {
		t.Fatal("answered without GitHub")
	}
}
