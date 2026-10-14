package main

import (
	"fmt"

	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/update"
)

// staleSE refuses a command run by an se built from a commit main has moved
// past, naming the command that updates it; why says what the stale se would
// get wrong. A take would hand its sub-agents the agents and guidance of the
// box's start; a retro's collect and report would read and store the window
// by the rules of a build main has moved past. Where it cannot tell (the build
// or its checkout unknown, main not fetched), it lets the command go.
func staleSE(w *World, why string) error {
	built, repo := builtFrom(w), pluginCheckout(w)
	if built == "" || repo == "" || !update.IsCheckout(w.Disk, repo) {
		return nil
	}
	git := func(args ...string) (string, error) {
		return proc.Output(w.Proc, proc.Cmd{Name: "git", Args: args, Dir: repo})
	}
	if _, err := git("fetch", "-q", "origin", "main"); err != nil {
		return nil
	}
	main, err := git("rev-parse", "origin/main")
	if err != nil || main == built {
		return nil
	}
	// --is-ancestor exits 1 where main is not in the build, and 128 where
	// it cannot tell, such as a build from a commit this checkout lacks.
	_, err = git("merge-base", "--is-ancestor", main, built)
	if code, _ := proc.ExitCode(err); code != 1 {
		return nil
	}
	return fmt.Errorf("se was built from %s, but main has moved on to %s: %s. Run se update (it pulls main into %s and rebuilds se), then run it again", short(built), short(main), why, repo)
}
