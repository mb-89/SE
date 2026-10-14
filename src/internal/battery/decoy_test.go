package battery_test

import (
	"os"
	"os/exec"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/modules/io/disk"
	ioenv "github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// machine is the disk git makes the decoy on: a process writes it, so no fake stands in.
var machine = disk.Real()

// realGit is the git that makes the decoy.
func realGit() git.Git { return git.Real(proc.Real(), ioenv.Real()) }

func TestDecoyUnchanged(t *testing.T) {
	t.Parallel()
	decoy, err := battery.NewDecoy(machine, realGit(), t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := decoy.Check(); err != nil {
		t.Fatal(err)
	}
}

// A git that inherits the decoy's GIT_DIR acts on the decoy, wherever it runs.
func TestDecoyCatchesInheritedGitDir(t *testing.T) {
	t.Parallel()
	decoy, err := battery.NewDecoy(machine, realGit(), t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "start")
	cmd.Dir = t.TempDir()
	cmd.Env = decoy.Env(os.Environ())
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, out)
	}
	err = decoy.Check()
	if err == nil || !strings.Contains(err.Error(), "refs/heads/decoy") {
		t.Fatalf("Check = %v, want the decoy's branch named", err)
	}
}
