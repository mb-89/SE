package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// recordedIssues answers the issue commands' gh calls for o/r: #1 claimed,
// #2 blocked by #1, #3 ready, #4 a pull request, #9 does not exist; a new
// issue comes back as #10. It answers the calls made, in order.
func recordedIssues(t *testing.T) *[][]string {
	t.Helper()
	answers := map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100": `[
			{"number":3,"title":"three","body":"do it","state":"open","html_url":"u3","issue_dependencies_summary":{"total_blocked_by":0}},
			{"number":2,"title":"two","body":"","state":"open","html_url":"u2","issue_dependencies_summary":{"total_blocked_by":1}},
			{"number":1,"title":"one","body":"","state":"open","html_url":"u1","issue_dependencies_summary":{"total_blocked_by":0}}]`,
		"repos/o/r/git/matching-refs/heads/issue-":                `[{"ref":"refs/heads/issue-1"}]`,
		"repos/o/r/issues/2/dependencies/blocked_by?per_page=100": `[{"number":1,"state":"open"}]`,
		"repos/o/r/issues/1":                                      `{"id":101,"number":1}`,
		"repos/o/r/issues/3":                                      `{"id":103,"number":3}`,
		"repos/o/r/issues/4":                                      `{"id":104,"number":4,"pull_request":{}}`,
		"repos/o/r/issues":                                        `{"id":110,"number":10,"title":"ten","html_url":"u10"}`,
		"repos/o/r/issues/10/dependencies/blocked_by":             `{"id":101}`,
	}
	var calls [][]string
	old := gh
	gh = func(args ...string) ([]byte, error) {
		calls = append(calls, args)
		path := args[len(args)-1]
		if path == "repos/o/r/issues/9" {
			return nil, errors.New("gh api repos/o/r/issues/9: exit status 1: gh: Not Found (HTTP 404)")
		}
		a, ok := answers[path]
		if !ok {
			return nil, fmt.Errorf("not recorded: %v", args)
		}
		return []byte(a), nil
	}
	t.Cleanup(func() { gh = old })
	return &calls
}

func TestIssueNextNamesTheNextReadyIssue(t *testing.T) {
	recordedIssues(t)
	code, out, errs := se(t, "issue", "next", "--repo", "o/r")
	if code != 0 || out != "#3 three\nu3\n\ndo it\n" {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, out, _ = se(t, "issue", "next", "--json", "--repo", "o/r")
	var answer struct {
		Ready bool
		Issue struct{ Number int }
	}
	if err := json.Unmarshal([]byte(out), &answer); code != 0 || err != nil || !answer.Ready || answer.Issue.Number != 3 {
		t.Fatalf("exit %d, %q %v", code, out, err)
	}
}

func TestIssueCommandsAreOfferedInASession(t *testing.T) {
	recordedIssues(t)
	if r := session(t, "issue", "next", "--repo", "o/r"); !strings.HasPrefix(r.Text, "#3 three") {
		t.Fatalf("%+v", r)
	}
	if r := session(t, "issue", "next", "--take", "--repo", "o/r"); !strings.Contains(r.Text, "not from a session") {
		t.Fatalf("%+v", r)
	}
	if r := session(t, "issue", "new", "--title", "t", "--body", "b", "--blocked-by", "none", "--repo", "o/r"); r.Text != "Created #10 ten\nu10" {
		t.Fatalf("%+v", r)
	}
	if r := session(t, "issue"); r.Text != "/se issue takes a word: new, next." {
		t.Fatalf("%+v", r)
	}
	if r := session(t, "help"); !strings.Contains(r.Text, "/se issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none") {
		t.Fatalf("%+v", r)
	}
}

func TestIssueTakeIsNoCommand(t *testing.T) {
	code, _, errs := se(t, "issue")
	if code != 2 || strings.TrimSpace(errs) != "se issue takes a word: new, next." {
		t.Fatalf("exit %d, %q", code, errs)
	}
	if _, taken := commands["issue take"]; taken {
		t.Fatal("issue take is registered; it is issue next --take")
	}
	if code, _, errs := se(t, "issue", "take", "3"); code != 2 || !strings.Contains(errs, "se issue takes a word: new, next.") {
		t.Fatalf("exit %d, %q", code, errs)
	}
}

func TestIssueNextTakeRefusesABadNumber(t *testing.T) {
	recordedIssues(t)
	for _, args := range [][]string{{"3"}, {"--take", "x"}, {"--take", "3", "4"}, {"--take=0"}, {"--take", "0"}, {"--take=x"}} {
		code, _, errs := se(t, append([]string{"issue", "next", "--repo", "o/r"}, args...)...)
		if code != 1 || !strings.Contains(errs, "one issue number") {
			t.Errorf("%v: exit %d, %q", args, code, errs)
		}
	}
	for _, args := range [][]string{{"--take", "2"}, {"--take=2"}, {"--take", "#2", "--json"}} {
		code, _, errs := se(t, append([]string{"issue", "next", "--repo", "o/r", "--workspace", t.TempDir()}, args...)...)
		if code != 1 || !strings.Contains(errs, "#2 is not ready: blocked by #1") {
			t.Fatalf("%v: exit %d, %q", args, code, errs)
		}
	}
}

func TestIssueNewNeedsBlockedBy(t *testing.T) {
	calls := recordedIssues(t)
	for args, want := range map[string]string{
		"--title t --body b":                              "needs --blocked-by",
		"--title t --body b --blocked-by=":                "--blocked-by is required",
		"--title t --body b --blocked-by 1,x":             "issue numbers",
		"--title t --blocked-by none":                     "one of --body and --body-file",
		"--title t --body b --body-file f --blocked-by 1": "one of --body and --body-file",
		"--body b --blocked-by none":                      "needs a --title",
		"--title t --body b --blocked-by 1,9":             "#9 does not exist in o/r",
		"--title t --body b --blocked-by 4":               "#4 is a pull request",
	} {
		code, _, errs := se(t, append([]string{"issue", "new", "--repo", "o/r"}, strings.Fields(args)...)...)
		if code != 1 || !strings.Contains(errs, want) {
			t.Errorf("%s: exit %d, %q, want %q", args, code, errs, want)
		}
	}
	for _, c := range *calls {
		if strings.Contains(strings.Join(c, " "), "POST") {
			t.Fatalf("a refused issue new wrote %v", c)
		}
	}
}

func TestIssueNewCreatesTheIssueAndItsLinks(t *testing.T) {
	calls := recordedIssues(t)
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "body.md"), []byte("the body\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	code, out, errs := se(t, "issue", "new", "--workspace", dir, "--repo", "o/r", "--title", "ten",
		"--body-file", "body.md", "--blocked-by", "3,#1,3")
	if code != 0 || out != "Created #10 ten\nu10\nBlocked by #1, #3.\n" {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	want := [][]string{
		{"api", "repos/o/r/issues/1"},
		{"api", "repos/o/r/issues/3"},
		{"api", "-X", "POST", "-f", "title=ten", "-f", "body=the body\n", "-f", "labels[]=se", "repos/o/r/issues"},
		{"api", "-X", "POST", "-F", "issue_id=101", "repos/o/r/issues/10/dependencies/blocked_by"},
		{"api", "-X", "POST", "-F", "issue_id=103", "repos/o/r/issues/10/dependencies/blocked_by"},
	}
	if !reflect.DeepEqual(*calls, want) {
		t.Fatalf("gh calls\n%q\nwant\n%q", *calls, want)
	}
	code, out, _ = se(t, "issue", "new", "--json", "--repo", "o/r", "--title", "ten", "--body", "b", "--blocked-by", "none")
	if code != 0 || out != `{"number":10,"url":"u10","blocked_by":[]}`+"\n" {
		t.Fatalf("exit %d, %q", code, out)
	}
}
