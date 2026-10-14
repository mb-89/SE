package rules_test

import (
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
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
	d, root := disk.NewFake(), filepath.FromSlash("/checkout")
	var paths []string
	for p, text := range files {
		full := filepath.Join(root, filepath.FromSlash(p))
		if err := d.MkdirAll(filepath.Dir(full)); err != nil {
			t.Fatal(err)
		}
		if err := d.WriteFile(full, []byte(text)); err != nil {
			t.Fatal(err)
		}
		paths = append(paths, p)
	}
	repo.Root, repo.Disk, repo.Paths = root, d, append(paths, "gone_test.go")
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

// TestEveryRuleIsRegisteredWithItsParts reads its want from the registry, so
// adding a rule edits no list here: each registered rule has its parts and a
// test of this package that names it.
func TestEveryRuleIsRegisteredWithItsParts(t *testing.T) {
	t.Parallel()
	tests, err := filepath.Glob("*_test.go")
	if err != nil {
		t.Fatal(err)
	}
	var named strings.Builder
	for _, f := range tests {
		if f == "rules_test.go" {
			continue
		}
		text, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		named.Write(text)
	}
	all := rules.Rules()
	if len(all) == 0 {
		t.Fatal("no rule is registered")
	}
	for _, r := range all {
		if r.Doc == "" || r.Applies == nil || r.Check == nil {
			t.Errorf("%s lacks a part: %+v", r.Name, r)
		}
		if !regexp.MustCompile(`^[a-z]+(-[a-z]+)*$`).MatchString(r.Name) {
			t.Errorf("rule %q is not named in lower-case words joined by dashes", r.Name)
		}
		if !strings.Contains(named.String(), strconv.Quote(r.Name)) {
			t.Errorf("rule %s has no test in this package that names it", r.Name)
		}
	}
}
