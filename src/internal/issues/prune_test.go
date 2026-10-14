// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
)

const allPullsPath = "repos/o/r/pulls?state=open&per_page=100"

// strayWorld is a recorded o/r with branches of every kind: issue-19 (closed,
// no PR), issue-20 (closed, open PR), issue-21 (open), issue-x (no issue's),
// claude/old (3 hours old, no PR), claude/pr (old, open PR) and claude/new
// (half an hour old, no PR).
func strayWorld(t *testing.T) *world {
	w := newWorld(t, nil)
	refs := func(names ...string) string {
		var rs []string
		for _, n := range names {
			rs = append(rs, fmt.Sprintf(`{"ref":"refs/heads/%s","object":{"sha":"s-%s"}}`, n, strings.ReplaceAll(n, "/", "-")))
		}
		return "[" + strings.Join(rs, ",") + "]"
	}
	w.set(refsPath, refs("issue-19", "issue-20", "issue-21", "issue-x"))
	w.set("repos/o/r/git/matching-refs/heads/claude/", refs("claude/old", "claude/pr", "claude/new"))
	w.set(allPullsPath, `[{"number":90,"head":{"ref":"issue-20"}},{"number":91,"head":{"ref":"claude/pr"}}]`)
	w.set("repos/o/r/issues/19", `{"number":19,"state":"closed"}`)
	w.set("repos/o/r/issues/21", `{"number":21,"state":"open"}`)
	commit := func(sha, at string) {
		w.set("repos/o/r/commits/"+sha, fmt.Sprintf(`{"commit":{"committer":{"date":%q}}}`, at))
	}
	commit("s-claude-old", quiet)
	commit("s-claude-new", recent)
	return w
}

func TestPruneListsOnlyStrayBranches(t *testing.T) {
	t.Parallel()
	w := strayWorld(t)
	s := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}
	got, err := s.Strays()
	if err != nil {
		t.Fatal(err)
	}
	want := []Stray{
		{Branch: "claude/old", SHA: "s-claude-old", Why: "its last commit is from 2026-10-13T09:00:00Z and it has no open PR"},
		{Branch: "issue-19", SHA: "s-issue-19", Why: "#19 is closed and issue-19 has no open PR"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v", got)
	}
	// Listing deletes nothing.
	if len(w.Writes()) != 0 {
		t.Fatalf("writes %q", w.Writes())
	}
	done, err := s.Prune(got)
	if err != nil || !done[0].Deleted || !done[1].Deleted {
		t.Fatalf("%+v %v", done, err)
	}
	if got, want := w.Writes(), []string{"DELETE repos/o/r/git/refs/heads/claude/old", "DELETE repos/o/r/git/refs/heads/issue-19"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("writes %q", got)
	}
	// Pruned, they are stray no more.
	if got, err := s.Strays(); err != nil || len(got) != 0 {
		t.Fatalf("%+v %v", got, err)
	}
}
