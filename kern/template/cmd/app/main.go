// Command app is this application: the core with its Go components compiled in.
// It has none yet; each component's package registers itself with
// index.Register, so adding one is an import here and an instance in wiring.toml.
package main

import (
	"os"

	"github.com/mb-89/kern/cli"
	// The application's Go components, one blank import each:
	// _ "example.com/app/components/<name>"
)

func main() { os.Exit(cli.Run("app", os.Args[1:], os.Stdout, os.Stderr)) }
