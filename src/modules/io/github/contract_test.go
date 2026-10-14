package github_test

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/modules/io/github"
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

type ref struct {
	Ref    string `json:"ref"`
	Object struct {
		SHA string `json:"sha"`
	} `json:"object"`
}

type pull struct {
	Number int    `json:"number"`
	NodeID string `json:"node_id"`
	Title  string `json:"title"`
	Body   string `json:"body"`
	State  string `json:"state"`
	Merged bool   `json:"merged"`
	Head   struct {
		Ref string `json:"ref"`
	} `json:"head"`
	Base struct {
		Ref string `json:"ref"`
	} `json:"base"`
}

type status struct {
	State       string `json:"state"`
	Context     string `json:"context"`
	Description string `json:"description"`
	Creator     struct {
		Login string `json:"login"`
	} `json:"creator"`
}

type comment struct {
	ID   int64  `json:"id"`
	Body string `json:"body"`
}

// contract is the one suite every GitHub keeps, the fake as the real one.
// fresh answers a GitHub and the OWNER/NAME of a repository it may write
// issues, comments, labels, branches and pull requests to; the repository has
// a main branch. What a case makes it cleans up: issues and PRs closed,
// branches deleted.
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
	t.Run("a branch with a commit opens a pull request, which closes, and the branch is deleted", func(t *testing.T) {
		gh, repo := fresh(t)
		// The branch is named for an issue of its own: numbers are never given twice.
		branch := fmt.Sprintf("%s-%d", label, create(t, gh, repo, "a branch's issue").Number)
		heads := fmt.Sprintf("repos/%s/git/matching-refs/heads/", repo)
		var main string
		for _, r := range list[ref](t, gh, heads+"main") {
			if r.Ref == "refs/heads/main" {
				main = r.Object.SHA
			}
		}
		if main == "" {
			t.Fatal("the repository has no main branch")
		}
		send(t, gh, "POST", fmt.Sprintf("repos/%s/git/refs", repo), github.F("ref", "refs/heads/"+branch), github.F("sha", main))
		t.Cleanup(func() { _, _ = gh.Send("DELETE", fmt.Sprintf("repos/%s/git/refs/heads/%s", repo, branch)) })
		if _, err := gh.Send("POST", fmt.Sprintf("repos/%s/git/refs", repo), github.F("ref", "refs/heads/"+branch), github.F("sha", main)); github.Status(err) != 422 {
			t.Fatalf("a branch made twice: %v", err)
		}
		var wrote struct {
			Commit struct {
				SHA string `json:"sha"`
			} `json:"commit"`
		}
		decode(t, send(t, gh, "PUT", fmt.Sprintf("repos/%s/contents/%s/%s.md", repo, label, branch),
			github.F("message", "a commit for the contract"), github.F("branch", branch),
			github.F("content", base64.StdEncoding.EncodeToString([]byte("written by the contract\n")))), &wrote)
		refs := list[ref](t, gh, heads+branch)
		if len(refs) != 1 || refs[0].Ref != "refs/heads/"+branch || refs[0].Object.SHA != wrote.Commit.SHA || wrote.Commit.SHA == main {
			t.Fatalf("refs %+v after the commit %s", refs, wrote.Commit.SHA)
		}

		// A status on the commit is read back, newest first, with who posted
		// it, and that account writes to the repository.
		statuses := fmt.Sprintf("repos/%s/commits/%s/statuses?per_page=100", repo, wrote.Commit.SHA)
		if got := list[status](t, gh, statuses); len(got) != 0 {
			t.Fatalf("a new commit's statuses: %+v", got)
		}
		for _, state := range []string{"pending", "success"} {
			send(t, gh, "POST", fmt.Sprintf("repos/%s/statuses/%s", repo, wrote.Commit.SHA),
				github.F("state", state), github.F("context", label), github.F("description", "the contract's "+state))
		}
		if _, err := gh.Send("POST", fmt.Sprintf("repos/%s/statuses/%s", repo, wrote.Commit.SHA), github.F("state", "green")); github.Status(err) != 422 {
			t.Fatalf("a status of no known state: %v", err)
		}
		got := list[status](t, gh, statuses)
		if len(got) != 2 || got[0].State != "success" || got[0].Context != label || got[0].Description != "the contract's success" || got[1].State != "pending" || got[0].Creator.Login == "" {
			t.Fatalf("statuses %+v", got)
		}
		perm := get[struct {
			Permission string `json:"permission"`
		}](t, gh, fmt.Sprintf("repos/%s/collaborators/%s/permission", repo, got[0].Creator.Login))
		if perm.Permission != "admin" && perm.Permission != "write" {
			t.Fatalf("%s, who posted the status, has %q access", got[0].Creator.Login, perm.Permission)
		}

		var p pull
		decode(t, send(t, gh, "POST", fmt.Sprintf("repos/%s/pulls", repo),
			github.F("title", "a contract PR"), github.F("head", branch), github.F("base", "main"), github.F("body", "its body")), &p)
		t.Cleanup(func() {
			_, _ = gh.Send("PATCH", fmt.Sprintf("repos/%s/pulls/%d", repo, p.Number), github.F("state", "closed"))
		})
		if p.Number == 0 || p.NodeID == "" || p.State != "open" || p.Head.Ref != branch || p.Base.Ref != "main" {
			t.Fatalf("opened %+v", p)
		}
		if _, err := gh.Send("POST", fmt.Sprintf("repos/%s/pulls", repo),
			github.F("title", "again"), github.F("head", branch), github.F("base", "main")); github.Status(err) != 422 {
			t.Fatalf("a second PR for one head: %v", err)
		}
		open := fmt.Sprintf("repos/%s/pulls?head=%s:%s&state=open&per_page=100", repo, owner(repo), branch)
		if got := list[pull](t, gh, open); len(got) != 1 || got[0].Number != p.Number {
			t.Fatalf("open pulls of %s: %+v", branch, got)
		}
		if got := get[pull](t, gh, fmt.Sprintf("repos/%s/pulls/%d", repo, p.Number)); got.Title != "a contract PR" || got.Body != "its body" || got.Head.Ref != branch {
			t.Fatalf("read back %+v", got)
		}

		send(t, gh, "PATCH", fmt.Sprintf("repos/%s/pulls/%d", repo, p.Number), github.F("state", "closed"))
		if got := get[pull](t, gh, fmt.Sprintf("repos/%s/pulls/%d", repo, p.Number)); got.State != "closed" || got.Merged {
			t.Fatalf("closed %+v", got)
		}
		if got := list[pull](t, gh, open); len(got) != 0 {
			t.Fatalf("a closed PR is still open: %+v", got)
		}
		send(t, gh, "DELETE", fmt.Sprintf("repos/%s/git/refs/heads/%s", repo, branch))
		if refs := list[ref](t, gh, heads+branch); len(refs) != 0 {
			t.Fatalf("a deleted branch is still there: %+v", refs)
		}
	})
	t.Run("an answer says the hour's quota, and each request is counted", func(t *testing.T) {
		gh, repo := fresh(t)
		before, _ := github.Metered(gh)
		list[struct{}](t, gh, fmt.Sprintf("repos/%s/git/matching-refs/heads/se-contract-never-", repo))
		n, r := github.Metered(gh)
		if n != before+1 || !r.Known || r.Limit <= 0 || r.Remaining >= r.Limit || r.Reset.IsZero() {
			t.Fatalf("after one request: %d counted, the quota %+v", n-before, r)
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
