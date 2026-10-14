// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// recordedFleet answers the fleet commands' gh calls for o/r: #3 is ready,
// nothing is claimed, and nothing is broken.
func recordedFleet(t *testing.T) *github.Fake {
	t.Helper()
	answers := map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100":      `[{"number":3,"title":"three","state":"open","html_url":"u3"}]`,
		"repos/o/r/git/matching-refs/heads/issue-":                `[]`,
		"repos/o/r/issues/3/dependencies/blocked_by?per_page=100": `[]`,
		"repos/o/r/pulls?state=open&per_page=100":                 `[]`,
	}
	return hubAt(t, answers)
}

// Where GitHub's answers say the hour's quota has fallen below the floor,
// fleet check says so on a last line, and in its JSON.
func TestFleetCheckSaysWhenTheQuotaRunsLow(t *testing.T) {
	t.Parallel()
	gh := recordedFleet(t)
	gh.Quota(1000, time.Hour)
	for range 850 {
		if _, err := gh.Get("repos/o/r/issues/3"); err != nil {
			t.Fatal(err)
		}
	}
	code, out, errs := se(t, "fleet", "check", "--repo", "o/r")
	if code != 0 || !strings.HasPrefix(out, "healthy\nGitHub's quota runs low: ") || !strings.Contains(out, " of the hour's 1000 requests left, under the 20% floor (github/config/quota-floor)") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	_, out, _ = se(t, "fleet", "check", "--json", "--repo", "o/r")
	var answer struct{ Quota string }
	if err := json.Unmarshal([]byte(out), &answer); err != nil || !strings.HasPrefix(answer.Quota, "GitHub's quota runs low: ") {
		t.Fatalf("%q %v", out, err)
	}
}

func TestAHealthyFleetSaysSo(t *testing.T) {
	t.Parallel()
	recordedFleet(t)
	for _, cmd := range []string{"check", "fix"} {
		if code, out, errs := se(t, "fleet", cmd, "--repo", "o/r"); code != 0 || out != "healthy\n" {
			t.Fatalf("fleet %s: exit %d, %q %q", cmd, code, out, errs)
		}
	}
	code, out, _ := se(t, "fleet", "check", "--json", "--repo", "o/r")
	var answer struct {
		Healthy  bool
		Findings []any
	}
	if err := json.Unmarshal([]byte(out), &answer); code != 0 || err != nil || !answer.Healthy || answer.Findings == nil || len(answer.Findings) != 0 {
		t.Fatalf("exit %d, %q %v", code, out, err)
	}
	if r := session(t, "fleet", "check", "--repo", "o/r"); r.Text != "healthy" {
		t.Fatalf("%+v", r)
	}
}

func TestFleetPruneDeletesOnlyWithApply(t *testing.T) {
	t.Parallel()
	answers := map[string]string{
		"repos/o/r/pulls?state=open&per_page=100":   `[]`,
		"repos/o/r/git/matching-refs/heads/issue-":  `[{"ref":"refs/heads/issue-19","object":{"sha":"c19"}}]`,
		"repos/o/r/git/matching-refs/heads/claude/": `[]`,
		"repos/o/r/issues/19":                       `{"number":19,"state":"closed"}`,
	}
	gh := hubAt(t, answers)
	if code, out, errs := se(t, "fleet", "prune", "--repo", "o/r"); code != 0 || out != "stray issue-19 at c19: #19 is closed and issue-19 has no open PR\n" || len(gh.Writes()) != 0 {
		t.Fatalf("exit %d, %q %q, writes %q", code, out, errs, gh.Writes())
	}
	if code, out, errs := se(t, "fleet", "prune", "--apply", "--repo", "o/r"); code != 0 || out != "deleted issue-19 at c19: #19 is closed and issue-19 has no open PR\n" ||
		!reflect.DeepEqual(gh.Writes(), []string{"DELETE repos/o/r/git/refs/heads/issue-19"}) {
		t.Fatalf("exit %d, %q %q, writes %q", code, out, errs, gh.Writes())
	}
	// The branch is gone, so a second prune finds nothing.
	if code, out, _ := se(t, "fleet", "prune", "--apply", "--repo", "o/r"); code != 0 || out != "no stray branches\n" {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestRulesOnBuildsTheMergesSeAndAnswersItsRuleAndTestFindingsWithoutTimings(t *testing.T) {
	t.Parallel()
	m := proc.NewFake()
	bin := filepath.Join("/wt", ".se", ".runtime", "se-rules")
	m.Install("go", func(proc.Cmd) int { return 0 })
	m.Install(bin, func(c proc.Cmd) int {
		fmt.Fprintln(c.Stderr, "se: 1 findings:\nx_test.go:3: fast-test: TestX does not call t.Parallel first\ncheck: rule fast-test took 12ms")
		return 1
	})
	got, err := rulesOn(m, "/wt")
	if err != nil || got != "se: 1 findings:\nx_test.go:3: fast-test: TestX does not call t.Parallel first" {
		t.Fatalf("%q %v", got, err)
	}
	src := filepath.Join("/wt", "src")
	tests := "go -C " + src + " test " + strings.Join(mergeTests, " ")
	if want := []string{"go -C " + src + " build -o " + bin + " ./cmd/se", bin + " rules --workspace /wt", tests}; !reflect.DeepEqual(m.Lines(), want) {
		t.Fatalf("ran %q", m.Lines())
	}
	m.Install(bin, func(proc.Cmd) int { return 0 })
	if got, err := rulesOn(m, "/wt"); got != "" || err != nil {
		t.Fatalf("%q %v", got, err)
	}
	m.Install("go", func(c proc.Cmd) int {
		if c.Args[2] != "test" {
			return 0
		}
		_, _ = fmt.Fprint(c.Stdout, "--- FAIL: TestEveryInteractiveCommandKeepsItsBudget (0.31s)\n    --- FAIL: TestEveryInteractiveCommandKeepsItsBudget/briefing (1.20s)\n"+
			"        budget_test.go:91: se briefing took 1300ms\nFAIL\nFAIL\tgithub.com/mb-89/SE/src/cmd/se\t6.012s\nok  \tgithub.com/mb-89/SE/src/internal/battery\t(cached)\nFAIL\n")
		return 1
	})
	want := "go test " + strings.Join(mergeTests, " ") + ":\n--- FAIL: TestEveryInteractiveCommandKeepsItsBudget\n    --- FAIL: TestEveryInteractiveCommandKeepsItsBudget/briefing\n" +
		"        budget_test.go:91: se briefing took 1300ms\nFAIL\nFAIL\tgithub.com/mb-89/SE/src/cmd/se\nFAIL"
	if got, err := rulesOn(m, "/wt"); got != want || err != nil {
		t.Fatalf("%q %v", got, err)
	}
	m.Install("go", func(c proc.Cmd) int {
		fmt.Fprintln(c.Stderr, "undefined: World")
		return 1
	})
	if got, err := rulesOn(m, "/wt"); got != "it does not build:\nundefined: World" || err != nil {
		t.Fatalf("%q %v", got, err)
	}
}

// TestTheRulesWorkflowRunsOnWhatTheMergeChecks holds that main's change to a
// rule, a battery step, a budget or the programs list reaches the open PRs it
// breaks before their CI does.
func TestTheRulesWorkflowRunsOnWhatTheMergeChecks(t *testing.T) {
	t.Parallel()
	// This reads the checkout's own workflow, so it reads the real disk.
	flow, err := disk.Real().ReadFile("../../../.github/workflows/rules.yml")
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range rulesWorkflowPaths {
		if !strings.Contains(string(flow), "\n      - "+p+"\n") {
			t.Errorf(".github/workflows/rules.yml does not run on changes to %s", p)
		}
	}
	for _, pkg := range mergeTests {
		dir := "src/" + strings.TrimSuffix(strings.TrimPrefix(pkg, "./"), "/...")
		// cmd/se's tests run on spec/budgets.yaml, not on se's every change.
		if dir != "src/cmd/se" && !slices.Contains(rulesWorkflowPaths, dir+"/**") {
			t.Errorf("se fleet rules tests %s, but the rules workflow does not run on its changes", pkg)
		}
	}
}
