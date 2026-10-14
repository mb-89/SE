// Package gitpaths lists the paths git tracks in a checkout, each once.
// git ls-files lists a path its index holds unmerged once per stage, so a
// conflicted file would count two or three times (#504).
package gitpaths

import (
	"bytes"
	"fmt"
	"strings"

	"github.com/mb-89/SE/src/internal/io/proc"
)

// Tracked answers the paths git's index at dir holds, slash-separated, each
// once whatever its stages, in git's order; with others, also the files git
// would track (not ignored, not yet added). It runs git on p.
func Tracked(p proc.Procs, dir string, others bool) ([]string, error) {
	args := []string{"ls-files", "-z", "--cached"}
	if others {
		args = append(args, "--others", "--exclude-standard")
	}
	var out bytes.Buffer
	if err := p.Run(proc.Cmd{Name: "git", Args: args, Dir: dir, Stdout: &out}); err != nil {
		return nil, fmt.Errorf("git ls-files: %w", err)
	}
	seen := map[string]bool{}
	var paths []string
	for _, f := range strings.Split(out.String(), "\x00") {
		if f != "" && !seen[f] {
			seen[f] = true
			paths = append(paths, f)
		}
	}
	return paths, nil
}
