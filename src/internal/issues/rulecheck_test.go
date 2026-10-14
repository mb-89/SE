// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// rulesPull is open PR n on branch as GitHub lists it.
func rulesPull(n int, branch string) string {
	return fmt.Sprintf(`{"number":%d,"head":{"ref":%q,"sha":"listed"},"base":{"ref":"main"}}`, n, branch)
}

// branchWith pushes branch from main of the clone a, with one file of text.
func branchWith(t *testing.T, a, branch, file, text string) {
	t.Helper()
	run(t, a, "checkout", "-q", "-b", branch, "main")
	if err := os.WriteFile(filepath.Join(a, file), []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, a, "add", file)
	run(t, a, "commit", "-q", "-m", branch)
	run(t, a, "push", "-q", "origin", branch)
	run(t, a, "checkout", "-q", "main")
}

// banned is the check of a rule main takes after the PRs opened: no file
// named bad, where the merge holds the rule.
func banned(dir string) (string, error) {
	if _, err := os.Stat(filepath.Join(dir, "rule")); err != nil {
		return "", nil
	}
	if _, err := os.Stat(filepath.Join(dir, "bad")); err == nil {
		return "bad:1: no-bad: no file is named bad", nil
	}
	return "", nil
}

func TestRulesNamesOnEachOpenPRTheRuleMainTookThatItBreaks(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	branchWith(t, a, "issue-1", "good", "fine")
	branchWith(t, a, "issue-2", "bad", "breaks the rule to come")
	branchWith(t, a, "issue-3", "rule", "its own rule, which conflicts with main's")
	branchWith(t, a, "claude/x", "bad", "no se PR")
	// Main takes the rule after the PRs opened.
	branchWith(t, a, "rules", "rule", "no file is named bad")
	run(t, a, "push", "-q", "origin", "rules:main")
	gh := recorded(t, map[string]string{
		openPullsPath: "[" + strings.Join([]string{rulesPull(10, "issue-1"), rulesPull(20, "issue-2"), rulesPull(30, "issue-3"), rulesPull(40, "claude/x")}, ",") + "]",
	})
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	got, err := s.Rules(a, banned)
	if err != nil {
		t.Fatal(err)
	}
	dids := map[int]string{}
	for _, r := range got {
		dids[r.PR] = r.Did
	}
	want := map[int]string{
		10: "passes se rules merged with main",
		20: "breaks se rules merged with main: told on the PR what to fix",
		30: "left to its takeover: it conflicts with main",
	}
	if !reflect.DeepEqual(dids, want) {
		t.Fatalf("got %v", dids)
	}
	if w := gh.Writes(); !reflect.DeepEqual(w, []string{"POST repos/o/r/issues/20/comments"}) {
		t.Fatalf("writes %q", w)
	}
	notes, err := gh.List("repos/o/r/issues/20/comments?per_page=100")
	if err != nil || !strings.Contains(string(notes), "no-bad: no file is named bad") || !strings.Contains(string(notes), "Merge origin/main into issue-2") {
		t.Fatalf("%s %v", notes, err)
	}
	// Each merge's worktree is gone, and the clone is as it was.
	if _, err := os.Stat(filepath.Join(a, filepath.FromSlash(RulesDir), "issue-2")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("worktree left: %v", err)
	}
	if st := run(t, a, "status", "--porcelain"); st != "" {
		t.Fatalf("the clone changed: %s", st)
	}
	// The same findings again are not told twice.
	if _, err := s.Rules(a, banned); err != nil {
		t.Fatal(err)
	}
	if w := gh.Writes(); len(w) != 1 {
		t.Fatalf("writes %q", w)
	}
}

func TestRulesReportsAFailedCheckAndChecksTheRest(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	branchWith(t, a, "issue-1", "one", "1")
	branchWith(t, a, "issue-2", "two", "2")
	gh := recorded(t, map[string]string{openPullsPath: "[" + rulesPull(10, "issue-1") + "," + rulesPull(20, "issue-2") + "]"})
	calls := 0
	check := func(dir string) (string, error) {
		calls++
		if calls == 1 {
			return "", errors.New("no go")
		}
		return "", nil
	}
	got, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Rules(a, check)
	if err == nil || !strings.Contains(err.Error(), "PR #10") || len(got) != 2 || got[0].Failed != "no go" || got[1].Did != "passes se rules merged with main" {
		t.Fatalf("%+v %v", got, err)
	}
}
