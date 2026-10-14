package github_test

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// The real GitHub keeps the contract against a repository of its own, which
// SE_GITHUB_CONTRACT_REPO names (OWNER/NAME), with gh logged in to write
// there: the contract opens issues in it, labelled se-contract, and closes
// them again. Without one it is skipped, since no repository SE works in is
// written to by a test.
func TestTheRealGitHubKeepsTheContract(t *testing.T) {
	t.Parallel()
	repo := os.Getenv("SE_GITHUB_CONTRACT_REPO")
	if repo == "" {
		t.Skip("SE_GITHUB_CONTRACT_REPO names no repository to write to")
	}
	contract(t, func(*testing.T) (github.GitHub, string) { return github.Real(), repo })
}

// A stand-in gh on the PATH shows how Real speaks to gh: the arguments it
// passes, the pages it asks for by repos/ path and joins, and the status it reads out of a refusal.
func TestTheRealGitHubSpeaksGh(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the stand-in gh is a shell script")
	}
	dir := t.TempDir()
	said := filepath.Join(dir, "said")
	script := "#!/bin/sh\nprintf '%s\\n' \"$@\" >>" + said + "\n" +
		"case \"$*\" in\n" +
		"*missing*) echo 'gh: Not Found (HTTP 404)' >&2; exit 1 ;;\n" +
		"*login*) echo 'To get started with GitHub CLI, please run:  gh auth login' >&2; exit 4 ;;\n" +
		"*per_page=2\\&page=1*) echo '[1,2]' ;;\n" +
		"*per_page=2\\&page=2*) echo '[3]' ;;\n" +
		"*refs*) echo '[9]' ;;\n" +
		"*) echo '{\"number\":5}' ;;\n" +
		"esac\n"
	if err := os.WriteFile(filepath.Join(dir, "gh"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	gh := github.Real()
	if out, err := gh.List("repos/o/r/issues?per_page=2"); err != nil || string(out) != "[1,2,3]" {
		t.Fatalf("%s %v", out, err)
	}
	if out, err := gh.List("repos/o/r/refs?per_page=1"); err != nil || string(out) != "[9]" {
		t.Fatalf("a list that takes no page: %s %v", out, err)
	}
	if out, err := gh.Get("repos/o/r/issues/5"); err != nil || !strings.Contains(string(out), `"number":5`) {
		t.Fatalf("%s %v", out, err)
	}
	if _, err := gh.Send("POST", "repos/o/r/issues/5/sub_issues", github.Int("sub_issue_id", 7), github.F("labels[]", "se")); err != nil {
		t.Fatal(err)
	}
	if _, err := gh.GraphQL("mutation", github.F("id", "PR_1")); err != nil {
		t.Fatal(err)
	}
	_, err := gh.Get("repos/o/r/issues/missing")
	if github.Status(err) != 404 || !strings.Contains(err.Error(), "HTTP 404") {
		t.Fatalf("%v", err)
	}
	if _, err := gh.Get("repos/o/r/login"); err == nil || err.Error() != "gh cannot reach GitHub without a login; run gh auth login, then this command again" {
		t.Fatalf("without a login: %v", err)
	}
	got, err := os.ReadFile(said)
	if err != nil {
		t.Fatal(err)
	}
	want := strings.Join([]string{
		"api", "repos/o/r/issues?per_page=2&page=1",
		"api", "repos/o/r/issues?per_page=2&page=2",
		"api", "repos/o/r/refs?per_page=1&page=1",
		"api", "repos/o/r/refs?per_page=1&page=2",
		"api", "repos/o/r/issues/5",
		"api", "-X", "POST", "-F", "sub_issue_id=7", "-f", "labels[]=se", "repos/o/r/issues/5/sub_issues",
		"api", "-f", "query=mutation", "-f", "id=PR_1", "graphql",
		"api", "repos/o/r/issues/missing",
		"api", "repos/o/r/login",
	}, "\n") + "\n"
	if string(got) != want {
		t.Fatalf("gh was passed\n%s\nwant\n%s", got, want)
	}
}
