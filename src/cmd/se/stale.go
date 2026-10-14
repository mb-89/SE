package main

import (
	"fmt"

	"github.com/mb-89/SE/src/internal/update"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// staleSE refuses a take by an se built from a commit main has moved past,
// naming the command that updates it: the agents and guidance a take hands
// over come from the SE that takes, so a box that ran on while main moved
// would hand its sub-agents the procedures of its start. Where it cannot tell
// (the build or its checkout unknown, main not fetched), it lets the take go.
func staleSE(w *World) error {
	built, repo := builtFrom(w), pluginCheckout(w)
	if built == "" || repo == "" || !update.IsCheckout(w.Disk, repo) {
		return nil
	}
	run := func(args ...string) (string, error) { return git.Output(w.Git, repo, args...) }
	if _, err := run("fetch", "-q", "origin", "main"); err != nil {
		return nil
	}
	main, err := run("rev-parse", "origin/main")
	if err != nil || main == built {
		return nil
	}
	// --is-ancestor exits 1 where main is not in the build, and 128 where
	// it cannot tell, such as a build from a commit this checkout lacks.
	_, err = run("merge-base", "--is-ancestor", main, built)
	if code, _ := proc.ExitCode(err); code != 1 {
		return nil
	}
	return fmt.Errorf("se was built from %s, but main has moved on to %s: a take would hand over stale agents and guidance. Run se update (it pulls main into %s and rebuilds se), then take again", short(built), short(main), repo)
}
