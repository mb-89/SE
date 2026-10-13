// Command rules checks the checkout it runs in against every registered SE
// rule (src/internal/rules). tests/check.sh runs it; it names each finding by
// file, line and rule, reports each rule's duration, and fails on a finding.
package main

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/rules"
)

func main() {
	// The files git tracks or would track: ignored ones, like .se/.runtime, are not SE's.
	out, err := exec.Command("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard").Output()
	if err != nil {
		fmt.Fprintf(os.Stderr, "rules: git ls-files: %v\n", err)
		os.Exit(1)
	}
	paths := strings.Split(strings.TrimRight(string(out), "\x00"), "\x00")
	results, err := rules.Run(".", paths)
	if err != nil {
		fmt.Fprintf(os.Stderr, "rules: %v\n", err)
		os.Exit(1)
	}
	failed := false
	for _, r := range results {
		for _, f := range r.Findings {
			fmt.Fprintln(os.Stderr, f)
			failed = true
		}
		fmt.Printf("check: rule %s took %dms\n", r.Rule.Name, r.Took.Round(time.Millisecond).Milliseconds())
	}
	if failed {
		os.Exit(1)
	}
}
