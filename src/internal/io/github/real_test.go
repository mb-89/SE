package github_test

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// The real GitHub keeps the contract against a repository of its own, which
// SE_GITHUB_CONTRACT_REPO names (OWNER/NAME), with a token (gh's) that
// writes there: the contract opens issues in it, labelled se-contract, and closes
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

// A stand-in API on loopback shows how Real speaks to GitHub: the token it
// sends, the pages it asks for by repos/ path and joins, the JSON a write and
// a GraphQL query carry, the answer it keeps and asks again with its ETag,
// and the status and message it reads out of a refusal.
func TestTheRealGitHubSpeaksRest(t *testing.T) {
	t.Parallel()
	var mu sync.Mutex
	var said []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		mu.Lock()
		said = append(said, strings.TrimSpace(fmt.Sprintf("%s %s %s %s", r.Header.Get("Authorization"), r.Method, r.URL.RequestURI(), body)))
		mu.Unlock()
		switch q := r.URL.RequestURI(); {
		case strings.Contains(q, "missing"):
			w.WriteHeader(404)
			fmt.Fprint(w, `{"message":"Not Found"}`)
		case strings.Contains(q, "invalid"):
			w.WriteHeader(422)
			fmt.Fprint(w, `{"message":"Validation Failed","errors":[{"code":"custom","message":"already linked"}]}`)
		case r.Method == "DELETE":
			w.WriteHeader(204)
		case strings.Contains(q, "per_page=2&page=1"):
			fmt.Fprint(w, `[1,2]`)
		case strings.Contains(q, "per_page=2&page=2"):
			fmt.Fprint(w, `[3]`)
		case strings.Contains(q, "refs"):
			fmt.Fprint(w, `[9]`)
		case q == "/graphql" && strings.Contains(string(body), "clean"):
			fmt.Fprint(w, `{"data":null,"errors":[{"message":"Pull request is in clean status"}]}`)
		case r.Header.Get("If-None-Match") == `"v1"`:
			w.WriteHeader(304)
		default:
			w.Header().Set("ETag", `"v1"`)
			fmt.Fprint(w, `{"number":5}`)
		}
	}))
	defer srv.Close()
	gh := github.RealAt(srv.URL, "tok")
	if out, err := gh.List("repos/o/r/issues?per_page=2"); err != nil || string(out) != "[1,2,3]" {
		t.Fatalf("%s %v", out, err)
	}
	if out, err := gh.List("repos/o/r/refs?per_page=1"); err != nil || string(out) != "[9]" {
		t.Fatalf("a list that takes no page: %s %v", out, err)
	}
	for range 2 {
		if out, err := gh.Get("repos/o/r/issues/5"); err != nil || string(out) != `{"number":5}` {
			t.Fatalf("an answer asked again: %s %v", out, err)
		}
	}
	if _, err := gh.Send("POST", "repos/o/r/issues/5/sub_issues", github.Int("sub_issue_id", 7), github.F("labels[]", "se"), github.F("labels[]", "x")); err != nil {
		t.Fatal(err)
	}
	if out, err := gh.Send("DELETE", "repos/o/r/git/refs/heads/b"); err != nil || len(out) != 0 {
		t.Fatalf("%q %v", out, err)
	}
	if _, err := gh.GraphQL("mutation", github.F("id", "PR_1")); err != nil {
		t.Fatal(err)
	}
	if _, err := gh.GraphQL("clean", github.F("id", "PR_1")); err == nil || !strings.Contains(err.Error(), "clean status") {
		t.Fatalf("a GraphQL error: %v", err)
	}
	_, err := gh.Get("repos/o/r/issues/missing")
	if github.Status(err) != 404 || !strings.Contains(err.Error(), "Not Found (HTTP 404)") {
		t.Fatalf("%v", err)
	}
	_, err = gh.Send("POST", "repos/o/r/issues/invalid", github.F("body", "b"))
	if github.Status(err) != 422 || !strings.Contains(err.Error(), "Validation Failed: already linked") {
		t.Fatalf("%v", err)
	}
	want := []string{
		"token tok GET /repos/o/r/issues?per_page=2&page=1",
		"token tok GET /repos/o/r/issues?per_page=2&page=2",
		"token tok GET /repos/o/r/refs?per_page=1&page=1",
		"token tok GET /repos/o/r/refs?per_page=1&page=2",
		"token tok GET /repos/o/r/issues/5",
		"token tok GET /repos/o/r/issues/5",
		`token tok POST /repos/o/r/issues/5/sub_issues {"labels":["se","x"],"sub_issue_id":7}`,
		"token tok DELETE /repos/o/r/git/refs/heads/b",
		`token tok POST /graphql {"query":"mutation","variables":{"id":"PR_1"}}`,
		`token tok POST /graphql {"query":"clean","variables":{"id":"PR_1"}}`,
		"token tok GET /repos/o/r/issues/missing",
		`token tok POST /repos/o/r/issues/invalid {"body":"b"}`,
	}
	if got := strings.Join(said, "\n"); got != strings.Join(want, "\n") {
		t.Fatalf("the API was sent\n%s\nwant\n%s", got, strings.Join(want, "\n"))
	}
}
