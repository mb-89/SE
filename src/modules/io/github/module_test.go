package github_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/index/indextest"
	"github.com/mb-89/SE/src/modules/io/clock"
	"github.com/mb-89/SE/src/modules/io/github"
)

// The module's verbs reach the GitHub it was handed: a send is read back by
// a get and a list, and GitHub's refusal is the request's failure.
func TestTheModulesVerbsReachItsGitHub(t *testing.T) {
	t.Parallel()
	gh := github.NewFake(clock.NewFake(start))
	f, err := indextest.New(github.Module(gh))
	if err != nil {
		t.Fatal(err)
	}
	made, err := f.Serve("send", github.Send{Method: "POST", Path: "repos/o/r/issues", Fields: []github.Field{github.F("title", "A verb")}})
	if err != nil {
		t.Fatal(err)
	}
	var issue struct {
		Number int    `json:"number"`
		Title  string `json:"title"`
	}
	if err := json.Unmarshal(made.([]byte), &issue); err != nil || issue.Title != "A verb" {
		t.Fatalf("send answered %s (%v)", made, err)
	}
	got, err := f.Serve("get", github.Get{Path: "repos/o/r/issues/1"})
	if err != nil || !strings.Contains(string(got.([]byte)), `"A verb"`) {
		t.Fatalf("get answered %s, %v", got, err)
	}
	all, err := f.Serve("list", github.List{Path: "repos/o/r/issues?state=open"})
	if err != nil || !strings.HasPrefix(string(all.([]byte)), "[") || !strings.Contains(string(all.([]byte)), `"A verb"`) {
		t.Fatalf("list answered %s, %v", all, err)
	}
	if _, err := f.Serve("get", github.Get{Path: "repos/o/r/issues/99"}); github.Status(err) != 404 {
		t.Fatalf("a get of no issue answered %v, want GitHub's 404", err)
	}
	if _, err := f.Serve("get", "repos/o/r/issues/1"); err == nil {
		t.Fatal("get served a request that is no github.Get")
	}
}
