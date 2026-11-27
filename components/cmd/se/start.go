package main

import (
	"context"
	"flag"
	"fmt"

	"kern/cli"
	sestart "se/components/start"
)

// SE's session start in Go (package start, docs/start.md "Start and refresh"): the verbs that
// bootstrap.sh, setup.sh and setup.ps1 call, ported from scripts/se_start.py.

// startHooksVerb is the start's hooks step, bootstrap.sh at the session's start.
var startHooksVerb = cli.Verb{
	Name:  "start-hooks",
	Args:  "--se DIR [--root DIR]",
	Hosts: true,
	Doc:   "point an unset core.hooksPath of the project at se's hooks, as setup.sh does; a set one stays",
	Flags: func(fs *flag.FlagSet) {
		fs.String("se", "", "SE's checkout whose hooks a project that pins no se gets")
		fs.String("root", "", "the project; default: $CLAUDE_PROJECT_DIR or the nearest ancestor with se.toml")
	},
	Run: func(c *cli.Call) int {
		if c.String("se") == "" {
			fmt.Fprintln(c.Stderr, "se start-hooks: --se names SE's checkout")
			return 2
		}
		if line := sestart.SetHooks(context.Background(), c.String("se"), sestart.Project(c.String("root"))); line != "" {
			fmt.Fprintln(c.Stdout, line)
		}
		return 0
	},
}

// stoppedHooksVerb names a checkout's own hooks before setup.sh and setup.ps1 set core.hooksPath.
var stoppedHooksVerb = cli.Verb{
	Name: "stopped-hooks",
	Args: "--repo DIR --hooks DIR",
	Doc:  "setup.sh and setup.ps1, before they set core.hooksPath: name the checkout's own hooks that stop running",
	Flags: func(fs *flag.FlagSet) {
		fs.String("repo", "", "the checkout")
		fs.String("hooks", "", "the folder core.hooksPath will name")
	},
	Run: func(c *cli.Call) int {
		repo, hooks := c.String("repo"), c.String("hooks")
		if repo == "" || hooks == "" {
			fmt.Fprintln(c.Stderr, "se stopped-hooks: --repo and --hooks are required")
			return 2
		}
		if line := sestart.StoppedHooks(context.Background(), repo, hooks); line != "" {
			fmt.Fprintln(c.Stdout, line)
		}
		return 0
	},
}
