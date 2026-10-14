package battery

import (
	"fmt"
	"strings"

	"github.com/mb-89/SE/src/internal/io/proc"
)

// ToolsScript pins the battery's linters; its fmt installs any that is
// missing or at another version, then runs their formatters.
const ToolsScript = "tests/tools.sh"

// Format runs every formatter the battery checks over dir, after installing
// any pinned linter it lacks, and answers what they said.
func Format(procs proc.Procs, dir string) (string, error) {
	cmd := proc.Cmd{Name: "sh", Args: []string{ToolsScript, "fmt"}, Dir: dir}
	out, err := proc.Combined(procs, cmd)
	said := strings.TrimSpace(string(out))
	if err != nil {
		return "", fmt.Errorf("%s: %v: %s", cmd, err, said)
	}
	return said, nil
}
