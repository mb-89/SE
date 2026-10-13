// se is SE's deterministic side: the workspace daemon the plugin forwards to,
// and the commands that start, stop and update it. Each command lives in a file
// of its own and registers itself; see commands.go.
package main

import "os"

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}
