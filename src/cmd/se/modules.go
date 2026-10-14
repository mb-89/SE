package main

import (
	"fmt"
	"sort"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/guidance"
	"github.com/mb-89/SE/src/internal/issues"
	"github.com/mb-89/SE/src/internal/reuse"
	"github.com/mb-89/SE/src/modules/io/clock"
	"github.com/mb-89/SE/src/modules/io/disk"
	"github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/github"
	sehttp "github.com/mb-89/SE/src/modules/io/http"
	"github.com/mb-89/SE/src/modules/io/proc"
	sessions "github.com/mb-89/SE/src/modules/io/session"
)

// modules are the modules se starts the index with, each I/O module handed
// its outside thing for the workspace p: the clock, the disk, the
// environment, git, GitHub through gh, the network, the programs, the
// session's posts and its log, the command line's own commands, the
// hand-over's switches, the issue work's config, and what each tier runs that
// others built. The wiring file binds them.
func modules(p daemon.Paths, clk clock.Clock, gh github.GitHub) []*index.Module {
	return []*index.Module{
		clock.Module(clk),
		disk.Module,
		env.Module,
		git.Module,
		github.Module(gh),
		sehttp.Module,
		proc.Module,
		sessions.Posts,
		sessions.LogModule(sessions.Folder(p.Disk, p.Logs())),
		cliModule(),
		guidance.Module,
		issues.Module,
		reuse.Module,
	}
}

// issueConfig is the issues instance's config, as the wiring file se carries
// gives it, which the help renders. A wiring that does not give it is a
// broken se, which the battery's tests catch before a merge.
func issueConfig() issues.Settings {
	s, err := issues.Configured()
	if err != nil {
		panic(err)
	}
	return s
}

// noInput is what a command of the command line reads on the index: nothing.
type noInput struct{}

// cliModule declares every command the command line registered, as the
// collector gathers it. The command line runs them itself; on the index they
// are declarations, which every adapter renders.
func cliModule() *index.Module {
	names := sortedNames()
	parts := make([]index.Part, 0, len(names)+1)
	parts = append(parts, index.Config(columnsKey, defaultColumns, "The most buttons a row of /se ui holds; the next button starts the next row."))
	for _, n := range names {
		decl := declOf(commands[n])
		parts = append(parts, index.Command(decl, func(noInput, index.Args) (index.Result, error) {
			return index.Result{}, fmt.Errorf("se %s runs in the se command line, not on the index", decl.Name)
		}))
	}
	return index.Declare("cli", "The se command line's own commands, which it runs itself.", parts...)
}

// declOf is a registered command as the index declares it: a command without
// a group stands under Other, one without details is helped by its summary,
// and every command takes --workspace.
func declOf(c Command) index.CommandDecl {
	d := index.CommandDecl{
		Name: c.Name, Usage: c.Usage, Summary: c.Summary, Help: c.Details, Group: c.Group,
		Session: c.Session, Button: c.Button, Installed: c.Installed, Class: c.Class,
		Flags: append([]index.Flag{workspaceFlag}, c.Flags...), Words: c.Words, JSON: c.JSON,
	}
	if d.Group == "" {
		d.Group = "Other"
	}
	if d.Help == "" {
		d.Help = d.Summary
	}
	return d
}

// catalog is the collector: what the modules se carries declare, as the
// wiring file binds them. It reads their declarations alone, so neither a
// run's clock nor its GitHub reaches it. The help, /se ui and the session's
// commands read it; a catalog that does not hold together is a broken se, which the
// battery's tests catch before a merge.
func catalog() index.Catalog {
	w, err := index.Wired()
	if err != nil {
		panic(err)
	}
	c, err := index.Collect(w, modules(daemon.Paths{}, clock.Real(), nil)...)
	if err != nil {
		panic(err)
	}
	return c
}

// sortedNames are the registered commands' names, sorted.
func sortedNames() []string {
	names := make([]string, 0, len(commands))
	for n := range commands {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}
