// Command se is SE's core: kern's index, bus and host carrying kern's GitHub
// component and SE's own components (components/README.md). Its commands
// are kern's (kern/cli): se start, status, stop, serve, hook.
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

func main() { os.Exit(cli.Run("se", os.Args[1:], os.Stdout, os.Stderr)) }
