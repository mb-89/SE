package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
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
			{"number":3,"title":"three","body":"do it","state":"open","html_url":"u3"},
			{"number":2,"title":"two","body":"","state":"open","html_url":"u2","issue_dependencies_summary":{"total_blocked_by":1}},
			{"number":1,"title":"one","body":"","state":"open","html_url":"u1"}]`,
		"repos/o/r/git/matching-refs/heads/issue-":                `[{"ref":"refs/heads/issue-1"}]`,
		"repos/o/r/issues/2/dependencies/blocked_by?per_page=100": `[{"number":1,"state":"open"}]`,
		"repos/o/r/issues/3/dependencies/blocked_by?per_page=100": `[]`,
		"repos/o/r/issues/1":                          `{"id":101,"number":1}`,
		"repos/o/r/issues/3":                          `{"id":103,"number":3}`,
		"repos/o/r/issues/4":                          `{"id":104,"number":4,"pull_request":{}}`,
		"repos/o/r/issues":                            `{"id":110,"number":10,"title":"ten","html_url":"u10"}`,
		"repos/o/r/issues/10/dependencies/blocked_by": `{"id":101}`,
	}
	var calls [][]string
	old, oldFire := gh, fire
	fire = func() string { t.Error("fired the routine without a claim"); return "" }
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
	t.Cleanup(func() { gh, fire = old, oldFire })
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
	if r := session(t, "issue", "new", "--title", "t", "--body", "b", "--blocked-by", "none", "--repo", "o/r"); r.Text != "Created #10 ten\nu10" {
		t.Fatalf("%+v", r)
	}
	if r := session(t, "help"); !strings.Contains(r.Text, "/se issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none") {
		t.Fatalf("%+v", r)
	}
	if r := session(t, "issue"); r.Text != "/se issue takes a word: land, new, next, review." {
		t.Fatalf("%+v", r)
	}
}

func TestIssueWithoutASubWordNamesThem(t *testing.T) {
	code, _, errs := se(t, "issue")
	if code != 2 || strings.TrimSpace(errs) != "se issue takes a word: land, new, next, review." {
		t.Fatalf("exit %d, %q", code, errs)
	}
}

func TestThereIsNoTakeCommand(t *testing.T) {
	if _, ok := commands["issue take"]; ok {
		t.Fatal("take is a flag of issue next, not a command")
	}
	if code, _, errs := se(t, "issue", "take"); code != 2 || !strings.Contains(errs, "se issue takes a word: land, new, next, review.") {
		t.Fatalf("exit %d, %q", code, errs)
	}
}

func TestIssueNextTakeRefusesABadNumber(t *testing.T) {
	recordedIssues(t)
	for _, args := range [][]string{{"3"}, {"--take", "x"}, {"--take", "3", "4"}, {"--take=3", "4"}, {"--take", "0"}} {
		code, _, errs := se(t, append([]string{"issue", "next", "--repo", "o/r"}, args...)...)
		if code != 1 || !strings.Contains(errs, "issue number") {
			t.Errorf("%v: exit %d, %q", args, code, errs)
		}
	}
	if code, _, errs := se(t, "issue", "next", "--take=x", "--repo", "o/r"); code != 1 || !strings.Contains(errs, `--take takes an issue number, not "x"`) {
		t.Errorf("exit %d, %q", code, errs)
	}
	// Each spelling of --take N reaches the claim of issue 2, which is blocked.
	for _, args := range [][]string{{"--take", "2"}, {"--take=2"}, {"--take", "#2"}, {"--take", "--json", "2"}} {
		code, _, errs := se(t, append([]string{"issue", "next", "--repo", "o/r", "--workspace", t.TempDir()}, args...)...)
		if code != 1 || !strings.Contains(errs, "#2 is not ready: blocked by #1") {
			t.Errorf("%v: exit %d, %q", args, code, errs)
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
		{"api", "--paginate", "repos/o/r/issues?labels=se&state=open&per_page=100"},
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

func TestIssueLandNamesThePR(t *testing.T) {
	root := t.TempDir()
	origin, ws := filepath.Join(root, "origin.git"), filepath.Join(root, "ws")
	git := func(dir string, args ...string) {
		t.Helper()
		if out, err := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	git(root, "init", "-q", "--bare", "-b", "main", origin)
	git(root, "clone", "-q", origin, ws)
	git(ws, "checkout", "-q", "-b", "issue-6")
	git(ws, "commit", "-q", "--allow-empty", "-m", "work")
	old, oldCheck, oldSession := gh, check, sessionID
	t.Cleanup(func() { gh, check, sessionID = old, oldCheck, oldSession })
	checked := ""
	check = func(dir string) error { checked = dir; return nil }
	sessionID = func() string { return "s1" }
	recorded := ""
	gh = func(args ...string) ([]byte, error) {
		switch args[len(args)-1] {
		case "repos/o/r/issues/6/comments?per_page=100":
			return []byte(`[{"body":` + strconv.Quote(recorded) + `}]`), nil
		case "repos/o/r/issues/6/comments":
			recorded = strings.TrimPrefix(args[len(args)-2], "body=")
			return []byte(`{}`), nil
		case "repos/o/r/issues?labels=se&state=open&per_page=100":
			return []byte(`[]`), nil
		case "repos/o/r/pulls?head=o:issue-6&base=main&state=open&per_page=100":
			return []byte(`[]`), nil
		case "repos/o/r/issues/6":
			return []byte(`{"number":6,"title":"six"}`), nil
		case "repos/o/r/pulls":
			return []byte(`{"number":14,"node_id":"PR_14","html_url":"u14"}`), nil
		case "graphql":
			return []byte(`{}`), nil
		}
		return nil, fmt.Errorf("not recorded: %v", args)
	}
	code, out, errs := se(t, "issue", "land", "--workspace", ws, "--repo", "o/r")
	if code != 0 || out != "Pushed issue-6 and opened PR #14, auto-merge (squash) on.\nu14\n" || checked != ws {
		t.Fatalf("exit %d, %q %q, checked %q", code, out, errs, checked)
	}
	code, out, _ = se(t, "issue", "land", "--json", "--workspace", ws, "--repo", "o/r")
	if code != 0 || out != `{"issue":6,"number":14,"url":"u14","created":true,"merged":false}`+"\n" {
		t.Fatalf("exit %d, %q", code, out)
	}
	// The leaf records its worker once, however often it lands.
	if want := "Worked by session s1 in " + ws + "."; !strings.HasPrefix(recorded, want) || !strings.Contains(recorded, `<!-- se-worker {"session":"s1","workspace":`) {
		t.Fatalf("recorded %q", recorded)
	}
}

func TestIssueNextInNamesTheTreesReadyLeaves(t *testing.T) {
	old := gh
	t.Cleanup(func() { gh = old })
	answers := map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100": `[
			{"number":1,"title":"root","state":"open","html_url":"u1","sub_issues_summary":{"total":2}},
			{"number":2,"title":"two","state":"open","html_url":"u2"},
			{"number":3,"title":"three","state":"open","html_url":"u3","labels":[{"name":"se-review"}],"sub_issues_summary":{"total":1}}]`,
		"repos/o/r/git/matching-refs/heads/issue-":   `[]`,
		"repos/o/r/issues/1/sub_issues?per_page=100": `[{"number":2,"state":"open"},{"number":3,"state":"open"}]`,
		"repos/o/r/issues/3/sub_issues?per_page=100": `[{"number":4,"state":"closed"}]`,
	}
	for _, n := range []int{1, 2, 3} {
		answers[fmt.Sprintf("repos/o/r/issues/%d/dependencies/blocked_by?per_page=100", n)] = `[]`
	}
	gh = func(args ...string) ([]byte, error) {
		if a, ok := answers[args[len(args)-1]]; ok {
			return []byte(a), nil
		}
		return nil, fmt.Errorf("not recorded: %v", args)
	}
	code, out, errs := se(t, "issue", "next", "--repo", "o/r")
	if code != 0 || !strings.Contains(out, "#1 is a parent: it holds no work. Coordinate its tree: se issue next --in 1 --take") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, out, errs = se(t, "issue", "next", "--in", "1", "--repo", "o/r")
	if code != 0 || out != "Ready: #2 two\nu2\nReady for review: #3 three\nu3\n" {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, out, _ = se(t, "issue", "next", "--in", "1", "--json", "--repo", "o/r")
	if code != 0 || !strings.Contains(out, `"root":1,"closed":false,"ready":[{"number":2`) {
		t.Fatalf("exit %d, %q", code, out)
	}
	code, out, errs = se(t, "issue", "next", "--in", "3", "--repo", "o/r")
	if code != 0 || out != "Ready for review: #3 three\nu3\n" {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	// A take inside finds no leaf, and names the review and its reviewer's worktree.
	ws := filepath.Join(t.TempDir(), "SE")
	code, out, errs = se(t, "issue", "next", "--in", "3", "--take", "--json", "--repo", "o/r", "--workspace", ws)
	wt := "git fetch -q origin main \\u0026\\u0026 git worktree add --detach " + filepath.Join(filepath.Dir(ws), "review-3-1") + " origin/main"
	if code != 0 || !strings.HasPrefix(out, `{"ready":false,"closed":false,"review":[{"number":3,`) || !strings.Contains(out, `"worktree":"`+wt+`"`) {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, out, errs = se(t, "issue", "next", "--in", "3", "--take", "--repo", "o/r", "--workspace", ws)
	if code != 0 || !strings.HasPrefix(out, "Nothing inside #3 is ready.\n\nReady for review: #3 three\nu3\nA reviewer that worked none of its tree works in a fresh worktree:\ngit fetch") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
}

func TestIssueNewTakesAParent(t *testing.T) {
	calls := recordedIssues(t)
	code, out, errs := se(t, "issue", "new", "--repo", "o/r", "--title", "ten", "--body", "b", "--blocked-by", "none", "--parent", "3")
	if code != 1 || !strings.Contains(errs, "making it a sub-issue of #3") {
		// The recording holds no sub-issue endpoint, so the link fails after the create.
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	last := (*calls)[len(*calls)-1]
	if want := []string{"api", "-X", "POST", "-F", "sub_issue_id=110", "repos/o/r/issues/3/sub_issues"}; !reflect.DeepEqual(last, want) {
		t.Fatalf("%q", last)
	}
}

func TestAClaimFiresTheRoutineOnceAndNothingElseDoes(t *testing.T) {
	recordedIssues(t)
	root := t.TempDir()
	origin, ws := filepath.Join(root, "origin.git"), filepath.Join(root, "ws")
	git := func(dir string, args ...string) {
		t.Helper()
		if out, err := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	git(root, "init", "-q", "--bare", "-b", "main", origin)
	git(root, "clone", "-q", origin, ws)
	git(ws, "checkout", "-q", "-b", "main")
	git(ws, "commit", "-q", "--allow-empty", "-m", "start")
	git(ws, "push", "-q", "origin", "main")
	fires := 0
	fire = func() string { fires++; return "Fan-out fired the routine: s1" }
	// Naming an issue and failing to take one fire nothing.
	if code, _, _ := se(t, "issue", "next", "--repo", "o/r", "--workspace", ws); code != 0 || fires != 0 {
		t.Fatalf("exit %d, %d fires", code, fires)
	}
	if code, _, _ := se(t, "issue", "next", "--take", "2", "--repo", "o/r", "--workspace", ws); code != 1 || fires != 0 {
		t.Fatalf("exit %d, %d fires", code, fires)
	}
	code, out, errs := se(t, "issue", "next", "--take", "--repo", "o/r", "--workspace", ws)
	if code != 0 || fires != 1 || out != "Took #3 three, on branch issue-3.\nu3\nFan-out fired the routine: s1\n\ndo it\n" {
		t.Fatalf("exit %d, %d fires, %q %q", code, fires, out, errs)
	}
	// #3 is now claimed on origin, but the recorded refs do not say so: the
	// take is refused, moves on, finds nothing else and fires nothing.
	git(ws, "checkout", "-q", "main")
	if code, out, _ := se(t, "issue", "next", "--take", "--json", "--repo", "o/r", "--workspace", ws); code != 0 || fires != 1 || out != `{"ready":false}`+"\n" {
		t.Fatalf("exit %d, %d fires, %q", code, fires, out)
	}
}

func TestAFailedFireDoesNotFailTheClaim(t *testing.T) {
	recordedIssues(t)
	root := t.TempDir()
	origin, ws := filepath.Join(root, "origin.git"), filepath.Join(root, "ws")
	for _, args := range [][]string{{root, "init", "-q", "--bare", "-b", "main", origin}, {root, "clone", "-q", origin, ws},
		{ws, "checkout", "-q", "-b", "main"}, {ws, "commit", "-q", "--allow-empty", "-m", "start"}, {ws, "push", "-q", "origin", "main"}} {
		if out, err := exec.Command("git", append([]string{"-C", args[0], "-c", "user.name=t", "-c", "user.email=t@t"}, args[1:]...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	fire = func() string { return "Fan-out refused: 429 Too Many Requests" }
	code, out, _ := se(t, "issue", "next", "--take", "--json", "--repo", "o/r", "--workspace", ws)
	if code != 0 || !strings.Contains(out, `"ready":true`) || !strings.Contains(out, `"fanout":"Fan-out refused: 429 Too Many Requests"`) {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestIssueNewReviewLabelsItSeReview(t *testing.T) {
	calls := recordedIssues(t)
	code, out, errs := se(t, "issue", "new", "--repo", "o/r", "--title", "ten", "--body", "b", "--blocked-by", "none", "--review")
	if code != 0 || out != "Created #10 ten\nu10\nLabelled se-review: it is reviewed once its sub-issues have closed.\n" {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	last := (*calls)[len(*calls)-1]
	if want := []string{"api", "-X", "POST", "-f", "title=ten", "-f", "body=b", "-f", "labels[]=se", "-f", "labels[]=se-review", "repos/o/r/issues"}; !reflect.DeepEqual(last, want) {
		t.Fatalf("%q", last)
	}
}

func TestIssueReviewReadsItsWords(t *testing.T) {
	calls := recordedIssues(t)
	old := sessionID
	t.Cleanup(func() { sessionID = old })
	sessionID = func() string { return "" }
	for args, want := range map[string]string{
		"pass":                     "pass or fail, then an issue number",
		"maybe 3 --why x":          "pass or fail, then an issue number",
		"pass x --why x":           `an issue number, not "x"`,
		"pass 3 4 --why x":         "pass or fail, then an issue number",
		"pass 3":                   "needs --why",
		"fail 3 --why x":           "a fail needs a --fix",
		"--why x pass #3":          "CLAUDE_CODE_SESSION_ID is not set",
		"fail --why x 3 --fix a b": "pass or fail, then an issue number",
	} {
		code, _, errs := se(t, append([]string{"issue", "review", "--repo", "o/r"}, strings.Fields(args)...)...)
		if code != 1 || !strings.Contains(errs, want) {
			t.Errorf("%s: exit %d, %q, want %q", args, code, errs, want)
		}
	}
	for _, c := range *calls {
		if strings.Contains(strings.Join(c, " "), "-X") {
			t.Fatalf("a refused review wrote %v", c)
		}
	}
}
