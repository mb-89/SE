// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/issues"
)

// recordedFleet answers the fleet commands' gh calls for o/r: #3 is ready,
// nothing is claimed, and nothing is broken.
func recordedFleet(t *testing.T) {
	t.Helper()
	answers := map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100":      `[{"number":3,"title":"three","state":"open","html_url":"u3"}]`,
		"repos/o/r/git/matching-refs/heads/issue-":                `[]`,
		"repos/o/r/issues/3/dependencies/blocked_by?per_page=100": `[]`,
		"repos/o/r/pulls?state=open&per_page=100":                 `[]`,
	}
	hubAt(t, answers)
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

func TestRulesOnBuildsTheMergesSeAndAnswersItsFindingsWithoutTimings(t *testing.T) {
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
	if want := []string{"go -C " + filepath.Join("/wt", "src") + " build -o " + bin + " ./cmd/se", bin + " rules --workspace /wt"}; !reflect.DeepEqual(m.Lines(), want) {
		t.Fatalf("ran %q", m.Lines())
	}
	m.Install(bin, func(proc.Cmd) int { return 0 })
	if got, err := rulesOn(m, "/wt"); got != "" || err != nil {
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

func TestFleetTrustPassesOnlyAHeadCarryingTheBatterysStatusForItsTree(t *testing.T) {
	t.Parallel()
	const sha, tree = "1111111111111111111111111111111111111111", "2222222222222222222222222222222222222222"
	gh := hubAt(t, map[string]string{})
	trust := func() (int, string, string) {
		return se(t, "fleet", "trust", "--repo", "o/r", "--sha", sha, "--tree", tree)
	}
	// A push without SE: CI runs the battery.
	if code, out, errs := trust(); code == 0 || out != "" || !strings.Contains(errs, "not trusted, so CI runs the battery") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	// A box's push: CI passes without it.
	if _, err := gh.Send("POST", "repos/o/r/statuses/"+sha, github.F("state", "success"), github.F("context", issues.BatteryContext), github.F("description", issues.BatteryDescription(tree))); err != nil {
		t.Fatal(err)
	}
	if code, out, errs := trust(); code != 0 || !strings.HasPrefix(out, "trusted: "+sha+" passed the battery on tree "+tree) {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	if code, _, errs := se(t, "fleet", "trust", "--repo", "o/r", "--sha", sha); code == 0 || !strings.Contains(errs, "--tree TREE") {
		t.Fatalf("exit %d, %q", code, errs)
	}
}
