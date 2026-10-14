package github_test

import (
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/github"
)

var start = time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)

func TestTheFakeGitHubKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(*testing.T) (github.GitHub, string) { return github.NewFake(clock.NewFake(start)), "o/r" })
}

func seeded(t *testing.T, answers map[string]string) *github.Fake {
	t.Helper()
	f := github.NewFake(clock.NewFake(start))
	if err := f.Seed(answers); err != nil {
		t.Fatal(err)
	}
	return f
}

func TestTheFakeReadsRecordedAnswersAsTheRepository(t *testing.T) {
	t.Parallel()
	f := seeded(t, map[string]string{
		// #1 is a parent of #2, which is open, and #3, which is closed.
		"repos/o/r/issues?labels=se&state=open&per_page=100":  `[{"number":1,"title":"t1","sub_issues_summary":{"total":2}},{"number":2,"labels":[{"name":"x"}]}]`,
		"repos/o/r/issues/1/sub_issues?per_page=100":          `[{"number":2,"state":"open"},{"number":3,"state":"closed"}]`,
		"repos/o/r/issues/2/dependencies/blocked_by":          `[{"number":9,"state":"open"}]`,
		"repos/o/r/issues/2/comments?per_page=100":            `[{"id":40,"body":"hello"}]`,
		"repos/o/r/git/matching-refs/heads/issue-":            `[{"ref":"refs/heads/issue-2"}]`,
		"repos/o/r/pulls?head=o:issue-2&base=main&state=open": `[{"number":14,"node_id":"PR_14"}]`,
		"repos/o/r/activity?ref=refs/heads/issue-2":           `[{"timestamp":"2026-10-14T10:00:00Z"}]`,
	})
	for path, want := range map[string]string{
		"repos/o/r/issues?labels=se&state=open":         `"number":2`,
		"repos/o/r/issues/2":                            `{"name":"se"}`,
		"repos/o/r/issues/1":                            `"sub_issues_summary":{"completed":1,"percent_completed":50,"total":2}`,
		"repos/o/r/issues/9/dependencies/blocking":      `"number":2`,
		"repos/o/r/issues/2/comments":                   `"body":"hello"`,
		"repos/o/r/git/matching-refs/heads/issue-2":     `"ref":"refs/heads/issue-2"`,
		"repos/o/r/pulls?base=main&state=open":          `"number":14`,
		"repos/o/r/activity?ref=refs/heads/issue-2":     `"timestamp"`,
		"repos/o/r/git/matching-refs/heads/claude/":     `[]`,
		"repos/o/r/pulls?head=o:issue-3&state=open":     `[]`,
		"repos/o/r/issues?labels=se&state=closed":       `[]`,
		"repos/o/r/issues/1/dependencies/blocked_by":    `[]`,
		"repos/o/r/issues?labels=se,x&state=open":       `"number":2`,
		"repos/o/r/issues?labels=se-retro&state=closed": `[]`,
	} {
		out, err := f.Get(path)
		if err != nil || !strings.Contains(string(out), want) {
			t.Errorf("%s: %s %v, want %s", path, out, err, want)
		}
	}
	if _, err := f.Get("repos/o/r/activity?ref=refs/heads/issue-5"); github.Status(err) != 404 {
		t.Errorf("an answer nobody recorded: %v", err)
	}
	if err := github.NewFake(clock.NewFake(start)).Seed(map[string]string{"repos/o/r/issues": `{`}); err == nil {
		t.Error("seeded an answer that is no JSON")
	}
}

func TestTheFakeLandsAPullRequest(t *testing.T) {
	t.Parallel()
	f := seeded(t, map[string]string{"repos/o/r/git/matching-refs/heads/issue-": `[{"ref":"refs/heads/issue-6"}]`})
	out, err := f.Send("POST", "repos/o/r/pulls", github.F("title", "the work"), github.F("head", "issue-6"), github.F("base", "main"), github.F("body", "Fixes #6"))
	if err != nil || !strings.Contains(string(out), `"node_id":"PR_1"`) {
		t.Fatalf("%s %v", out, err)
	}
	if _, err := f.Send("POST", "repos/o/r/pulls", github.F("title", "again"), github.F("head", "issue-6"), github.F("base", "main")); github.Status(err) != 422 {
		t.Fatalf("a second PR for one head: %v", err)
	}
	if _, err := f.GraphQL("mutation { enablePullRequestAutoMerge }", github.F("id", "PR_1")); err != nil {
		t.Fatal(err)
	}
	if out, _ := f.Get("repos/o/r/pulls/1"); !strings.Contains(string(out), `"auto_merge":{"merge_method":"squash"}`) {
		t.Fatalf("%s", out)
	}
	if _, err := f.Send("PUT", "repos/o/r/pulls/1/merge", github.F("merge_method", "squash")); err != nil {
		t.Fatal(err)
	}
	if out, _ := f.List("repos/o/r/pulls?state=closed&base=main"); !strings.Contains(string(out), `"merged_at":"2026-10-14T12:00:00Z"`) {
		t.Fatalf("%s", out)
	}
	if out, _ := f.List("repos/o/r/pulls?state=open"); string(out) != "[]" {
		t.Fatalf("a merged PR is still open: %s", out)
	}
	if out, _ := f.Get("repos/o/r/issues/1"); !strings.Contains(string(out), `"pull_request"`) {
		t.Fatalf("a PR is an issue too: %s", out)
	}
	if _, err := f.Send("DELETE", "repos/o/r/git/refs/heads/issue-6"); err != nil {
		t.Fatal(err)
	}
	if out, _ := f.List("repos/o/r/git/matching-refs/heads/issue-"); string(out) != "[]" {
		t.Fatalf("a deleted branch is still there: %s", out)
	}
	want := []string{"POST repos/o/r/pulls", "POST repos/o/r/pulls", "POST graphql", "PUT repos/o/r/pulls/1/merge", "DELETE repos/o/r/git/refs/heads/issue-6"}
	if got := f.Writes(); !reflect.DeepEqual(got, want) {
		t.Fatalf("writes %q", got)
	}
}

func TestTheFakeRefusesAutoMergeAsGitHubDoes(t *testing.T) {
	t.Parallel()
	answers := map[string]string{"repos/o/r/pulls/14": `{"number":14,"node_id":"PR_14","state":"open","mergeable_state":"clean"}`}
	f := seeded(t, answers)
	if _, err := f.GraphQL("mutation { enablePullRequestAutoMerge }", github.F("id", "PR_14")); err == nil || !strings.Contains(err.Error(), "clean status") {
		t.Fatalf("a clean PR: %v", err)
	}
	f = seeded(t, map[string]string{"repos/o/r/pulls/14": `{"number":14,"node_id":"PR_14","state":"open"}`})
	f.NoAutoMerge = true
	if _, err := f.GraphQL("mutation { enablePullRequestAutoMerge }", github.F("id", "PR_14")); err == nil || !strings.Contains(err.Error(), "not allowed") {
		t.Fatalf("a repository without auto-merge: %v", err)
	}
	f = seeded(t, map[string]string{
		"repos/o/r/pulls/14":                       `{"number":14,"node_id":"PR_14","state":"open"}`,
		"repos/o/r/git/matching-refs/heads/issue-": `[{"ref":"refs/heads/issue-6"}]`,
	})
	f.Proxy = true
	if _, err := f.GraphQL("mutation { enablePullRequestAutoMerge }", github.F("id", "PR_14")); err == nil || !strings.Contains(err.Error(), "GraphQL is not available") {
		t.Fatalf("behind the proxy: %v", err)
	}
	if _, err := f.Send("PUT", "repos/o/r/pulls/14/ccr/auto_merge", github.F("merge_method", "squash")); err != nil {
		t.Fatal(err)
	}
	if _, err := f.Send("DELETE", "repos/o/r/git/refs/heads/issue-6"); github.Status(err) != 403 {
		t.Fatalf("deleting a branch behind the proxy: %v", err)
	}
}

func TestTheFakeStampsWhatItWritesByItsClock(t *testing.T) {
	t.Parallel()
	c := clock.NewFake(start)
	f := github.NewFake(c)
	out, err := f.Send("POST", "repos/o/r/issues", github.F("title", "t"), github.F("labels[]", "se"))
	if err != nil || !strings.Contains(string(out), `"created_at":"2026-10-14T12:00:00Z"`) {
		t.Fatalf("%s %v", out, err)
	}
	c.Advance(time.Hour)
	if out, err := f.Send("PATCH", "repos/o/r/issues/1", github.F("state", "closed")); err != nil || !strings.Contains(string(out), `"closed_at":"2026-10-14T13:00:00Z"`) {
		t.Fatalf("%s %v", out, err)
	}
	if out, _ := f.List("repos/o/r/issues?labels=se&state=closed&since=2026-10-14T12:30:00Z"); !strings.Contains(string(out), `"number":1`) {
		t.Fatalf("an issue closed inside the window: %s", out)
	}
	if out, _ := f.List("repos/o/r/issues?labels=se&state=closed&since=2026-10-14T13:30:00Z"); string(out) != "[]" {
		t.Fatalf("an issue closed before the window: %s", out)
	}
}

func TestADeletedIssueIsGoneAndItsNumberIsNeverGivenAgain(t *testing.T) {
	t.Parallel()
	f := seeded(t, map[string]string{"repos/o/r/issues/8": `{"number":8,"state":"open"}`})
	f.DeleteIssue("o/r", 9)
	if _, err := f.Get("repos/o/r/issues/9"); github.Status(err) != 410 {
		t.Fatalf("%v", err)
	}
	if out, err := f.Send("POST", "repos/o/r/issues", github.F("title", "t")); err != nil || !strings.Contains(string(out), `"number":10`) {
		t.Fatalf("%s %v", out, err)
	}
}

func TestTheFakeTakesABranchUpdateAndAWorkflowDispatch(t *testing.T) {
	t.Parallel()
	f := seeded(t, map[string]string{"repos/o/r/pulls/10": `{"number":10,"state":"open","head":{"ref":"issue-1","sha":"a1"}}`})
	if _, err := f.Send("PUT", "repos/o/r/pulls/10/update-branch", github.F("expected_head_sha", "a0")); github.Status(err) != 422 {
		t.Fatalf("an update from an old head: %v", err)
	}
	if _, err := f.Send("PUT", "repos/o/r/pulls/10/update-branch", github.F("expected_head_sha", "a1")); err != nil {
		t.Fatal(err)
	}
	if _, err := f.Send("POST", "repos/o/r/actions/workflows/ci.yml/dispatches", github.F("ref", "issue-1")); err != nil {
		t.Fatal(err)
	}
	if _, err := f.Send("POST", "repos/o/r/actions/workflows/ci.yml/dispatches"); github.Status(err) != 422 {
		t.Fatalf("a dispatch without a ref: %v", err)
	}
}

func TestTheFakeListsTheRepositorysCommentsSinceATimeByPage(t *testing.T) {
	t.Parallel()
	f := seeded(t, map[string]string{
		"repos/o/r/issues/1/comments": `[{"id":1,"body":"old","created_at":"2026-10-01T00:00:00Z"},{"id":3,"body":"new","created_at":"2026-10-03T00:00:00Z"}]`,
		"repos/o/r/issues/2/comments": `[{"id":2,"body":"mid","created_at":"2026-10-02T00:00:00Z"}]`,
	})
	out, err := f.List("repos/o/r/issues/comments?since=2026-10-02T00:00:00Z&per_page=1&page=2")
	if err != nil || !strings.Contains(string(out), `"body":"new"`) || !strings.Contains(string(out), `"issue_url":"https://api.github.com/repos/o/r/issues/1"`) || strings.Contains(string(out), "mid") {
		t.Fatalf("%s %v", out, err)
	}
	if out, _ := f.List("repos/o/r/issues/comments?since=2026-10-02T00:00:00Z&per_page=1&page=3"); string(out) != "[]" {
		t.Fatalf("past the last page: %s", out)
	}
}
