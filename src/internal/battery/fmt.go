package battery

import (
	"fmt"
	"os/exec"
	"strings"
)

// ToolsScript pins the battery's linters; its fmt installs any that is
// missing or at another version, then runs their formatters.
const ToolsScript = "tests/tools.sh"

// Format runs every formatter the battery checks over dir, after installing
// any pinned linter it lacks, and answers what they said.
func Format(dir string) (string, error) {
	cmd := exec.Command("sh", ToolsScript, "fmt")
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	said := strings.TrimSpace(string(out))
	if err != nil {
		return "", fmt.Errorf("sh %s fmt: %v: %s", ToolsScript, err, said)
	}
	return said, nil
}
