package rules_test

import (
	"testing"

	"github.com/mb-89/SE/src/internal/rules"
)

// surfaces is a checkout holding the files named, the rule's configuration
// with the allowlist given, and, at the root, the file check adds.
func surfaces(allowlist string, files ...string) map[string]string {
	out := map[string]string{
		rules.FiveConfig: "limit: 2\nsurfaces: [\".\", spec]\nallowlist:\n" + allowlist,
	}
	for _, f := range files {
		out[f] = "x"
	}
	return out
}

func TestASurfaceHoldsAtMostItsLimit(t *testing.T) {
	t.Parallel()
	found := check(t, "rule-of-five", surfaces("",
		// The root: four files, three folders (src holds the configuration), and dot entries that do not count.
		"README.md", "RUNME.sh", "CLAUDE.md", ".gitignore", ".github/ci.yml", "spec/a.md", "tests/check.sh",
		// spec/: two files, one folder, each within the limit.
		"spec/b.md", "spec/deep/c.md", "spec/deep/d.md",
		// What lies deeper does not count.
		"tests/x/1", "tests/x/2", "tests/x/3",
	))
	same(t, found, []string{
		rules.FiveConfig + ":1: rule-of-five: the root holds 4 visible files, more than 2",
		rules.FiveConfig + ":1: rule-of-five: the root holds 3 visible folders, more than 2",
	})
}

func TestTheFiveAllowlistOnlyShrinks(t *testing.T) {
	t.Parallel()
	found := check(t, "rule-of-five", surfaces(
		"  .: {files: 2, folders: 4}\n  spec: {files: 3}\n  tests: {files: 9}\n",
		"a", "b", "c", "spec/1", "spec/2", "spec/3", "spec/4", "s1/x", "s2/x", "s3/x",
	))
	same(t, found, []string{
		rules.FiveConfig + ":4: rule-of-five: the root holds 4 visible files, more than the 2 the allowlist allows",
		// src/ holds the configuration: five folders.
		rules.FiveConfig + ":4: rule-of-five: the root holds 5 visible folders, more than the 4",
		rules.FiveConfig + ":5: rule-of-five: spec/ holds 4 visible files, more than the 3",
		rules.FiveConfig + ":6: rule-of-five: the allowlist entry tests files names no surface",
	})
}

func TestAnEntryAboveTheCountIsLowered(t *testing.T) {
	t.Parallel()
	found := check(t, "rule-of-five", surfaces("  spec: {files: 9}\n  .: {files: 2}\n", "spec/1", "spec/2", "spec/3", "a"))
	same(t, found, []string{
		rules.FiveConfig + ":4: rule-of-five: spec/ holds 3 visible files: lower its allowlist entry from 9 to 3",
		rules.FiveConfig + ":5: rule-of-five: the root holds 2 visible files, within the limit: remove its allowlist entry",
	})
}

// During a merge, git lists a conflicted file once per unmerged stage (1, 2
// and 3): the rule of five counts it once.
func TestAnUnmergedFileCountsOnce(t *testing.T) {
	t.Parallel()
	five := "limit: 2\nsurfaces: [spec]\n"
	repo := &rules.Repo{Paths: []string{"spec/a.md", "spec/b.md", "spec/b.md", "spec/b.md", rules.FiveConfig}}
	for _, r := range rules.Rules() {
		if r.Name == "rule-of-five" {
			if found := r.Check(repo, rules.FiveConfig, []byte(five)); len(found) != 0 {
				t.Fatalf("spec/ holds 2 files, but the rule of five found %v", found)
			}
			return
		}
	}
	t.Fatal("no rule-of-five")
}
