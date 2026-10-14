package issues

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// ToolsScript pins the battery's linters; its install installs only those
// missing or at another version.
const ToolsScript = "tests/tools.sh"

// ReadyTools installs the pinned linters the pre-push check needs, so a fresh
// box's first claim is not refused by its own hook. It is a no-op where they
// stand, and where dir has no tools script.
func ReadyTools(dir string) error {
	if _, err := os.Stat(filepath.Join(dir, ToolsScript)); err != nil {
		return nil
	}
	cmd := exec.Command("sh", ToolsScript, "install")
	cmd.Dir = dir
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("the pre-push check needs the pinned linters, and sh %s install failed: %v: %s", ToolsScript, err, strings.TrimSpace(string(out)))
	}
	return nil
}
