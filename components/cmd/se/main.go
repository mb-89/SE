// Command se is SE's core: kern's index, bus and host carrying kern's GitHub
// component and SE's own components (components/README.md). Its commands
// are kern's (kern/cli): se start, status, stop, serve, hook, and se mcp, the
// MCP door (kern/mcp), whose greeting tool reads Greeting.
package main

import (
	"os"

	"github.com/mb-89/kern/cli"
	// kern's shared components and SE's own, one blank import each.
	_ "github.com/mb-89/kern/components/github"
	_ "github.com/mb-89/se/components/fleet"
	_ "github.com/mb-89/se/components/origin"
	_ "github.com/mb-89/se/components/retro-due"
)

// Greeting is what the MCP door's greeting tool reads, the live part of SE's
// start greeting (README "Start and refresh"): what is due, the retro and the
// fleet's findings. What is queued, `work_tickets.py queue`, syncs the
// checkout, so it is not read-only and stays out (the greeting only reads).
var Greeting = []string{"retro-due/due", "fleet/findings"}

func main() {
	cli.Greeting = Greeting
	os.Exit(cli.Run("se", os.Args[1:], os.Stdout, os.Stderr))
}
