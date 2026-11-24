// Command se is SE's core: kern's index, bus and host carrying kern's GitHub
// component and SE's own components (components/README.md), and SE's start:
// its commands are kern's (kern/cli) and se agent, which starts the SE agent
// with SE loaded from its clone (agent.go); a bare se is se agent at a
// terminal and the help elsewhere. `se help` lists every verb.
package main

import (
	"os"

	"kern/cli"
	// kern's shared components and SE's own, one blank import each.
	_ "kern/components/clock"
	_ "kern/components/github"
	_ "kern/components/session"
	_ "se/components/fleet"
	_ "se/components/origin"
	_ "se/components/retro-due"
	_ "se/components/template"
)

// Greeting is what the MCP door's greeting tool reads, the live part of SE's
// start greeting (docs/start.md "Start and refresh"): what is due, the retro and the
// fleet's findings. What is queued, `work_tickets.py queue`, syncs the
// checkout, so it is not read-only and stays out (the greeting only reads).
var Greeting = []string{"retro-due/due", "fleet/findings"}

func main() {
	cli.Greeting = Greeting
	cli.About = "se: SE's command line: the SE agent's start, and the core its hosts and hooks run"
	cli.Add(agentVerb)
	cli.Bare = bareVerb
	os.Exit(cli.Run("se", os.Args[1:], os.Stdout, os.Stderr))
}
