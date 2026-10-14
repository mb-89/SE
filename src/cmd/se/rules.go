package main

import (
	"flag"
	"fmt"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/rules"
)

func init() {
	register(Command{
		Name:    "rules",
		Usage:   "rules",
		Group:   "Checks",
		Summary: "check this checkout against every SE rule",
		Details: "check every file git tracks or would track against each rule in src/internal/rules, " +
			"naming each finding by file, line and rule, and how long each rule took. " +
			"The rules that read prose know se's commands and its manifests. It fails on a finding; tests/check.sh runs it.",
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("rules")); err != nil {
				return Reply{}, err
			}
			repo, err := repoOf(c.Workspace)
			if err != nil {
				return Reply{}, err
			}
			repo.Clock = c.Clock
			results, err := rules.Run(repo)
			if err != nil {
				return Reply{}, err
			}
			var lines, findings []string
			for _, r := range results {
				for _, f := range r.Findings {
					findings = append(findings, f.String())
				}
				lines = append(lines, fmt.Sprintf("check: rule %s took %dms", r.Rule.Name, r.Took.Round(time.Millisecond).Milliseconds()))
			}
			if len(findings) > 0 {
				return Reply{}, fmt.Errorf("%d findings:\n%s\n%s", len(findings), strings.Join(findings, "\n"), strings.Join(lines, "\n"))
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
}

// repoOf is the checkout at root as the rules see it: the files git tracks or
// would track (ignored ones, like .se/.runtime, are not SE's), the paths it
// ignores, se's commands and its manifests.
func repoOf(root string) (*rules.Repo, error) {
	out, err := exec.Command("git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").Output()
	if err != nil {
		return nil, fmt.Errorf("git ls-files: %w", err)
	}
	paths := strings.Split(strings.TrimRight(string(out), "\x00"), "\x00")
	return &rules.Repo{
		Root:  root,
		Paths: paths,
		// A folder git ignores by a pattern ending in / matches only as a
		// folder, which a fresh checkout may not hold: so p/ is asked too.
		Ignored: func(p string) bool {
			for _, q := range []string{p, p + "/"} {
				if exec.Command("git", "-C", root, "check-ignore", "-q", "--no-index", filepath.FromSlash(q)).Run() == nil {
					return true
				}
			}
			return false
		},
		Commands: commandFlags(),
		Manifest: func(name, at string) (string, error) { return manifest(root, paths, name, at) },
	}, nil
}

// unmergedPaths is every path git's index at root holds unmerged, each once:
// a conflicted file stands there once per stage, which would list it as often.
func unmergedPaths(root string) ([]string, error) {
	out, err := exec.Command("git", "-C", root, "diff", "--name-only", "--diff-filter=U", "-z").Output()
	if err != nil {
		return nil, fmt.Errorf("git diff --diff-filter=U: %w", err)
	}
	var paths []string
	for _, p := range strings.Split(string(out), "\x00") {
		if p != "" {
			paths = append(paths, p)
		}
	}
	return paths, nil
}

// commandFlags is every command by name, with the flags it takes.
func commandFlags() map[string][]string {
	out := map[string][]string{}
	for name, c := range commands {
		flags := []string{}
		if fs := flagsOf(c, false); fs != nil {
			fs.VisitAll(func(f *flag.Flag) { flags = append(flags, f.Name) })
		}
		out[name] = flags
	}
	return out
}
