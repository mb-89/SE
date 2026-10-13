package rules_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/rules"
)

// check writes files into a fresh folder and answers what the rule named found there.
func check(t *testing.T, rule string, files map[string]string) []string {
	t.Helper()
	return checkIn(t, &rules.Repo{}, rule, files)
}

// checkIn is check with what the repo knows beyond its files.
func checkIn(t *testing.T, repo *rules.Repo, rule string, files map[string]string) []string {
	t.Helper()
	root := t.TempDir()
	var paths []string
	for p, text := range files {
		full := filepath.Join(root, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(full, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
		paths = append(paths, p)
	}
	repo.Root, repo.Paths = root, append(paths, "gone_test.go")
	results, err := rules.Run(repo)
	if err != nil {
		t.Fatal(err)
	}
	var found []string
	ran := false
	for _, r := range results {
		if r.Rule.Name != rule {
			continue
		}
		ran = true
		for _, f := range r.Findings {
			found = append(found, f.String())
		}
	}
	if !ran {
		t.Fatalf("rule %s is not registered", rule)
	}
	return found
}

func TestEveryRuleIsRegisteredWithItsParts(t *testing.T) {
	var names []string
	for _, r := range rules.Rules() {
		if r.Doc == "" || r.Applies == nil || r.Check == nil {
			t.Errorf("%s lacks a part: %+v", r.Name, r)
		}
		names = append(names, r.Name)
	}
	if got := strings.Join(names, " "); got != "manifest reader repo-path se-command test-package todo-issue" {
		t.Fatalf("rules = %s", got)
	}
}
