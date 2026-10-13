// Package rules holds SE's own rules as checks. A rule is one file that calls
// register in its init, with a test beside it; tests/check.sh runs every
// registered rule through src/cmd/rules, so adding the file is all it takes.
package rules

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"time"
)

// Rule is one of SE's rules, checked file by file.
type Rule struct {
	// Name is what a finding names it by: "test-package".
	Name string
	// Doc says what it requires, in one line.
	Doc string
	// Applies says whether the rule reads the file at this slash-separated path.
	Applies func(path string) bool
	// Check answers what the file breaks, by line.
	Check func(path string, text []byte) []Finding
}

// Finding is one place a file breaks a rule.
type Finding struct {
	Path    string
	Line    int
	Rule    string
	Message string
}

func (f Finding) String() string {
	return fmt.Sprintf("%s:%d: %s: %s", f.Path, f.Line, f.Rule, f.Message)
}

// Result is what one rule found, and how long it took.
type Result struct {
	Rule     Rule
	Findings []Finding
	Took     time.Duration
}

var registered = map[string]Rule{}

func register(r Rule) {
	if _, dup := registered[r.Name]; dup {
		panic("rules: " + r.Name + " registered twice")
	}
	registered[r.Name] = r
}

// Rules answers every registered rule, by name.
func Rules() []Rule {
	all := make([]Rule, 0, len(registered))
	for _, r := range registered {
		all = append(all, r)
	}
	sort.Slice(all, func(i, j int) bool { return all[i].Name < all[j].Name })
	return all
}

// Run checks the files at paths, slash-separated and relative to root,
// against every registered rule. A path that is gone is skipped.
func Run(root string, paths []string) ([]Result, error) {
	texts := map[string][]byte{}
	read := func(p string) ([]byte, bool, error) {
		if t, ok := texts[p]; ok {
			return t, t != nil, nil
		}
		t, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(p)))
		if errors.Is(err, fs.ErrNotExist) {
			texts[p] = nil
			return nil, false, nil
		}
		if err != nil {
			return nil, false, err
		}
		texts[p] = t
		return t, true, nil
	}
	var results []Result
	for _, r := range Rules() {
		start := time.Now()
		res := Result{Rule: r}
		for _, p := range paths {
			if !r.Applies(p) {
				continue
			}
			t, ok, err := read(p)
			if err != nil {
				return nil, err
			}
			if ok {
				res.Findings = append(res.Findings, r.Check(p, t)...)
			}
		}
		res.Took = time.Since(start)
		results = append(results, res)
	}
	return results, nil
}
