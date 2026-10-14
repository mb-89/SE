// Package rules holds SE's own rules as checks. A rule is one file that calls
// register in its init, with a test beside it; tests/check.sh runs every
// registered rule through se rules, so adding the file is all it takes. A rule
// that can apply the mechanical part of its finding has a Fix, which
// se rules --fix runs.
package rules

import (
	"errors"
	"fmt"
	"io/fs"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
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
	Check func(repo *Repo, path string, text []byte) []Finding
	// Fix, where the rule has one, answers the file with the mechanical part
	// of its findings applied, and whether it changed; se rules --fix runs it.
	// What it leaves is still found.
	Fix func(repo *Repo, path string, text []byte) ([]byte, bool)
}

// Repo is what a rule may know beyond the file it reads: the checkout's
// files, and the owners its prose may name, which se fills in.
type Repo struct {
	// Root is the checkout's folder.
	Root string
	// Disk is what the checkout's files are read from.
	Disk disk.Disk
	// Paths are the files git tracks or would track, slash-separated and
	// relative to Root.
	Paths []string
	// Ignored says whether git ignores a path: a build output or a runtime
	// file, which prose may name though no checkout holds it. Nil ignores none.
	Ignored func(path string) bool
	// Commands are se's commands by name, each with the flags it takes,
	// without their dashes.
	Commands map[string][]string
	// Agents are the plugin's agents the registry of kinds names, each with
	// the role it holds.
	Agents map[string]string
	// Manifest answers the manifest named, as it stands in the file at path.
	Manifest func(name, path string) (string, error)
	// Clock times each rule; nil times none.
	Clock clock.Clock

	files, dirs map[string]bool
	texts       map[string][]byte
	// funcVars is test-swap's package-level func variables, by folder.
	funcVars map[string]map[string]bool
	// doors is io-module's declarations of the I/O modules.
	doors *doors
}

// Read answers the text of a slash-separated path relative to Root, read once
// per run, and whether it exists.
func (r *Repo) Read(p string) ([]byte, bool, error) {
	if t, ok := r.texts[p]; ok {
		return t, t != nil, nil
	}
	if r.texts == nil {
		r.texts = map[string][]byte{}
	}
	t, err := r.Disk.ReadFile(filepath.Join(r.Root, filepath.FromSlash(p)))
	if errors.Is(err, fs.ErrNotExist) {
		r.texts[p] = nil
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	r.texts[p] = t
	return t, true, nil
}

// Exists says whether a slash-separated path, relative to Root, is a file or
// a folder of the checkout, or one git ignores.
func (r *Repo) Exists(p string) bool {
	if r.files == nil {
		r.files, r.dirs = map[string]bool{}, map[string]bool{".": true}
		for _, f := range r.Paths {
			r.files[f] = true
			for d := path.Dir(f); d != "."; d = path.Dir(d) {
				r.dirs[d] = true
			}
		}
	}
	p = path.Clean(p)
	return r.files[p] || r.dirs[p] || (r.Ignored != nil && r.Ignored(p))
}

// Top says whether name is a folder at the checkout's top.
func (r *Repo) Top(name string) bool {
	return name != "." && !strings.Contains(name, "/") && r.Exists(name) && !r.files[name]
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

// Fix applies every rule's Fix to the repo's files, writing each file it
// changes, and answers what it changed, one "path: rule" each, in order.
func Fix(repo *Repo) ([]string, error) {
	var fixed []string
	for _, r := range Rules() {
		if r.Fix == nil {
			continue
		}
		for _, p := range repo.Paths {
			if !r.Applies(p) {
				continue
			}
			t, ok, err := repo.Read(p)
			if err != nil {
				return nil, err
			}
			if !ok {
				continue
			}
			out, changed := r.Fix(repo, p, t)
			if !changed {
				continue
			}
			if err := repo.Disk.WriteFile(filepath.Join(repo.Root, filepath.FromSlash(p)), out); err != nil {
				return nil, err
			}
			repo.texts[p] = out
			fixed = append(fixed, p+": "+r.Name)
		}
	}
	return fixed, nil
}

// Run checks the repo's files against every registered rule. A path that is
// gone is skipped.
func Run(repo *Repo) ([]Result, error) {
	var results []Result
	for _, r := range Rules() {
		var start time.Time
		if repo.Clock != nil {
			start = repo.Clock.Now()
		}
		res := Result{Rule: r}
		for _, p := range repo.Paths {
			if !r.Applies(p) {
				continue
			}
			t, ok, err := repo.Read(p)
			if err != nil {
				return nil, err
			}
			if ok {
				res.Findings = append(res.Findings, r.Check(repo, p, t)...)
			}
		}
		if repo.Clock != nil {
			res.Took = repo.Clock.Now().Sub(start)
		}
		results = append(results, res)
	}
	return results, nil
}
