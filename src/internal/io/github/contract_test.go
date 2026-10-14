package github_test

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// label marks what the contract writes, so it lists only its own issues.
const label = "se-contract"

type issue struct {
	ID          int64  `json:"id"`
	Number      int    `json:"number"`
	Title       string `json:"title"`
	Body        string `json:"body"`
	State       string `json:"state"`
	StateReason string `json:"state_reason"`
	Labels      []struct {
		Name string `json:"name"`
	} `json:"labels"`
	SubIssues *struct {
		Total     int `json:"total"`
		Completed int `json:"completed"`
	} `json:"sub_issues_summary"`
}

func (i issue) labelled(name string) bool {
	for _, l := range i.Labels {
		if l.Name == name {
			return true
		}
	}
	return false
}

type comment struct {
	ID   int64  `json:"id"`
	Body string `json:"body"`
}

// contract is the one suite every GitHub keeps, the fake as the real one.
// fresh answers a GitHub and the OWNER/NAME of a repository it may write
// issues, comments and labels to.
func contract(t *testing.T, fresh func(t *testing.T) (github.GitHub, string)) {
	t.Run("a created issue is read back and listed", func(t *testing.T) {
		gh, repo := fresh(t)
		i := create(t, gh, repo, "a created issue")
		got := get[issue](t, gh, fmt.Sprintf("repos/%s/issues/%d", repo, i.Number))
		if got.Title != "a created issue" || got.Body != "its body" || got.State != "open" || !got.labelled(label) || got.ID == 0 {
			t.Fatalf("read back %+v", got)
		}
		if !listed(t, gh, fmt.Sprintf("repos/%s/issues?labels=%s&state=open&per_page=100", repo, label), i.Number) {
			t.Fatalf("#%d is not in the open list of its label", i.Number)
		}
	})
	t.Run("a closed issue leaves the open list for the closed one", func(t *testing.T) {
		gh, repo := fresh(t)
		i := create(t, gh, repo, "an issue to close")
		send(t, gh, "PATCH", fmt.Sprintf("repos/%s/issues/%d", repo, i.Number), github.F("state", "closed"), github.F("state_reason", "completed"))
		got := get[issue](t, gh, fmt.Sprintf("repos/%s/issues/%d", repo, i.Number))
		if got.State != "closed" || got.StateReason != "completed" {
			t.Fatalf("read back %+v", got)
		}
		if listed(t, gh, fmt.Sprintf("repos/%s/issues?labels=%s&state=open&per_page=100", repo, label), i.Number) {
			t.Fatalf("closed #%d is still in the open list", i.Number)
		}
		if !listed(t, gh, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100", repo, label), i.Number) {
			t.Fatalf("closed #%d is not in the closed list", i.Number)
		}
	})
	t.Run("a comment is read back, edited and deleted", func(t *testing.T) {
		gh, repo := fresh(t)
		i := create(t, gh, repo, "an issue with comments")
		path := fmt.Sprintf("repos/%s/issues/%d/comments", repo, i.Number)
		var first, second comment
		decode(t, send(t, gh, "POST", path, github.F("body", "first")), &first)
		decode(t, send(t, gh, "POST", path, github.F("body", "second")), &second)
		if first.ID == 0 || second.ID <= first.ID || first.Body != "first" {
			t.Fatalf("posted %+v then %+v", first, second)
		}
		send(t, gh, "PATCH", fmt.Sprintf("repos/%s/issues/comments/%d", repo, first.ID), github.F("body", "first, edited"))
		send(t, gh, "DELETE", fmt.Sprintf("repos/%s/issues/comments/%d", repo, second.ID))
		got := list[comment](t, gh, path+"?per_page=100")
		if len(got) != 1 || got[0].ID != first.ID || got[0].Body != "first, edited" {
			t.Fatalf("read back %+v", got)
		}
	})
	t.Run("labels are added and taken off", func(t *testing.T) {
		gh, repo := fresh(t)
		i := create(t, gh, repo, "an issue to label")
		path := fmt.Sprintf("repos/%s/issues/%d", repo, i.Number)
		send(t, gh, "POST", path+"/labels", github.F("labels[]", label+"-more"))
		if got := get[issue](t, gh, path); !got.labelled(label) || !got.labelled(label+"-more") {
			t.Fatalf("labels %+v", got.Labels)
		}
		send(t, gh, "DELETE", path+"/labels/"+label+"-more")
		if got := get[issue](t, gh, path); !got.labelled(label) || got.labelled(label+"-more") {
			t.Fatalf("labels %+v", got.Labels)
		}
		if _, err := gh.Send("DELETE", path+"/labels/"+label+"-more"); github.Status(err) != 404 {
			t.Fatalf("taking off a label it lacks: %v", err)
		}
	})
	t.Run("a sub-issue is listed and counted on its parent", func(t *testing.T) {
		gh, repo := fresh(t)
		parent, sub := create(t, gh, repo, "a parent"), create(t, gh, repo, "its sub-issue")
		path := fmt.Sprintf("repos/%s/issues/%d", repo, parent.Number)
		send(t, gh, "POST", path+"/sub_issues", github.Int("sub_issue_id", sub.ID))
		if subs := list[issue](t, gh, path+"/sub_issues?per_page=100"); len(subs) != 1 || subs[0].Number != sub.Number {
			t.Fatalf("sub-issues %+v", subs)
		}
		if got := get[issue](t, gh, fmt.Sprintf("repos/%s/issues/%d/parent", repo, sub.Number)); got.Number != parent.Number {
			t.Fatalf("parent %+v", got)
		}
		if _, err := gh.Get(path + "/parent"); github.Status(err) != 404 {
			t.Fatalf("a parent's parent: %v", err)
		}
		send(t, gh, "PATCH", fmt.Sprintf("repos/%s/issues/%d", repo, sub.Number), github.F("state", "closed"))
		if got := get[issue](t, gh, path); got.SubIssues == nil || got.SubIssues.Total != 1 || got.SubIssues.Completed != 1 {
			t.Fatalf("summary %+v", got.SubIssues)
		}
	})
	t.Run("a blocked-by link is read from both ends", func(t *testing.T) {
		gh, repo := fresh(t)
		blocked, blocker := create(t, gh, repo, "a blocked issue"), create(t, gh, repo, "its blocker")
		send(t, gh, "POST", fmt.Sprintf("repos/%s/issues/%d/dependencies/blocked_by", repo, blocked.Number), github.Int("issue_id", blocker.ID))
		by := list[issue](t, gh, fmt.Sprintf("repos/%s/issues/%d/dependencies/blocked_by?per_page=100", repo, blocked.Number))
		if len(by) != 1 || by[0].Number != blocker.Number || by[0].State != "open" {
			t.Fatalf("blocked by %+v", by)
		}
		blocking := list[issue](t, gh, fmt.Sprintf("repos/%s/issues/%d/dependencies/blocking?per_page=100", repo, blocker.Number))
		if len(blocking) != 1 || blocking[0].Number != blocked.Number {
			t.Fatalf("blocking %+v", blocking)
		}
	})
	t.Run("what is not there is refused", func(t *testing.T) {
		gh, repo := fresh(t)
		if _, err := gh.Get(fmt.Sprintf("repos/%s/issues/999999999", repo)); github.Status(err) != 404 {
			t.Fatalf("a missing issue: %v", err)
		}
		if _, err := gh.Send("DELETE", fmt.Sprintf("repos/%s/git/refs/heads/se-contract-never", repo)); github.Status(err) != 422 {
			t.Fatalf("deleting a missing branch: %v", err)
		}
		if refs := list[struct{}](t, gh, fmt.Sprintf("repos/%s/git/matching-refs/heads/se-contract-never-", repo)); len(refs) != 0 {
			t.Fatalf("refs %+v", refs)
		}
		if pulls := list[struct{}](t, gh, fmt.Sprintf("repos/%s/pulls?head=%s:se-contract-never&state=all&per_page=100", repo, owner(repo))); len(pulls) != 0 {
			t.Fatalf("pulls %+v", pulls)
		}
	})
}

func owner(repo string) string {
	o, _, _ := strings.Cut(repo, "/")
	return o
}

// create opens an issue labelled for the contract, and closes it once the test is done.
func create(t *testing.T, gh github.GitHub, repo, title string) issue {
	t.Helper()
	var i issue
	decode(t, send(t, gh, "POST", fmt.Sprintf("repos/%s/issues", repo), github.F("title", title), github.F("body", "its body"), github.F("labels[]", label)), &i)
	if i.Number == 0 || i.ID == 0 {
		t.Fatalf("created %+v", i)
	}
	t.Cleanup(func() {
		_, _ = gh.Send("PATCH", fmt.Sprintf("repos/%s/issues/%d", repo, i.Number), github.F("state", "closed"))
	})
	return i
}

func send(t *testing.T, gh github.GitHub, method, path string, fields ...github.Field) []byte {
	t.Helper()
	out, err := gh.Send(method, path, fields...)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	return out
}

func get[T any](t *testing.T, gh github.GitHub, path string) T {
	t.Helper()
	out, err := gh.Get(path)
	if err != nil {
		t.Fatalf("%s: %v", path, err)
	}
	var v T
	decode(t, out, &v)
	return v
}

func list[T any](t *testing.T, gh github.GitHub, path string) []T {
	t.Helper()
	out, err := gh.List(path)
	if err != nil {
		t.Fatalf("%s: %v", path, err)
	}
	v := []T{}
	decode(t, out, &v)
	return v
}

func listed(t *testing.T, gh github.GitHub, path string, n int) bool {
	t.Helper()
	for _, i := range list[issue](t, gh, path) {
		if i.Number == n {
			return true
		}
	}
	return false
}

func decode(t *testing.T, data []byte, into any) {
	t.Helper()
	if err := json.Unmarshal(data, into); err != nil {
		t.Fatalf("%v: %s", err, data)
	}
}
