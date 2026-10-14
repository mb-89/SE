package main

import (
	"bytes"
	"flag"
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/issues"
	"github.com/mb-89/SE/src/internal/rules"
)

func init() {
	register(Command{
		Name:    "rules",
		Class:   batch,
		Usage:   "rules [--fix]",
		Group:   "Checks",
		Summary: "check this checkout against every SE rule",
		Details: []string{
			"check every file git tracks or would track against each rule in src/internal/rules, naming each finding by file, line and rule, and how long each rule took.",
			"The rules that read prose know se's commands and its manifests.",
			"It fails on a finding; tests/check.sh runs it.",
			"--fix first applies the mechanical part of each finding where the rule can, such as the fast-test rule's t.Parallel() as a test's first statement, names each file it changed, and then checks.",
		},
		Run: func(c *Call) (Reply, error) {
			fs := c.Flags("rules")
			fix := fs.Bool("fix", false, "apply the mechanical part of each finding where the rule can, then check")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			repo, err := repoOf(c.Disk, c.Proc, c.Workspace)
			if err != nil {
				return Reply{}, err
			}
			repo.Clock = c.Clock
			var lines, findings []string
			if *fix {
				fixed, err := rules.Fix(repo)
				if err != nil {
					return Reply{}, err
				}
				for _, f := range fixed {
					lines = append(lines, "fixed: "+f)
				}
			}
			results, err := rules.Run(repo)
			if err != nil {
				return Reply{}, err
			}
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
// ignores, se's commands and its manifests. It reads on d and runs git on procs.
func repoOf(d disk.Disk, procs proc.Procs, root string) (*rules.Repo, error) {
	var out bytes.Buffer
	if err := procs.Run(proc.Cmd{Name: "git", Args: []string{"ls-files", "-z", "--cached", "--others", "--exclude-standard"}, Dir: root, Stdout: &out}); err != nil {
		return nil, fmt.Errorf("git ls-files: %w", err)
	}
	paths := strings.Split(strings.TrimRight(out.String(), "\x00"), "\x00")
	return &rules.Repo{
		Root:  root,
		Disk:  d,
		Paths: paths,
		// A folder git ignores by a pattern ending in / matches only as a
		// folder, which a fresh checkout may not hold: so p/ is asked too.
		Ignored: func(p string) bool {
			for _, q := range []string{p, p + "/"} {
				if procs.Run(proc.Cmd{Name: "git", Args: []string{"check-ignore", "-q", "--no-index", filepath.FromSlash(q)}, Dir: root}) == nil {
					return true
				}
			}
			return false
		},
		Commands: commandFlags(),
		Agents:   issues.Agents(),
		Manifest: func(name, at string) (string, error) { return manifest(d, root, paths, name, at) },
	}, nil
}

// commandFlags is every command by name, with the flags it takes.
func commandFlags() map[string][]string {
	out := map[string][]string{}
	for _, c := range catalog().Commands {
		name, flags := c.Name, []string{}
		if fs := flagsOf(name, false); fs != nil {
			fs.VisitAll(func(f *flag.Flag) { flags = append(flags, f.Name) })
		}
		out[name] = flags
	}
	return out
}
