package battery_test

import (
	"os"
	"os/exec"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/gitenv"
	"github.com/mb-89/SE/src/internal/io/proc"
)

func TestDecoyUnchanged(t *testing.T) {
	decoy, err := battery.NewDecoy(proc.Real(), t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := decoy.Check(); err != nil {
		t.Fatal(err)
	}
}

// A git that inherits the decoy's GIT_DIR acts on the decoy, wherever it runs.
func TestDecoyCatchesInheritedGitDir(t *testing.T) {
	decoy, err := battery.NewDecoy(proc.Real(), t.TempDir())
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

func TestIsolated(t *testing.T) {
	env := []string{"HOME=/h", "GIT_DIR=/r/.git", "GIT_AUTHOR_NAME=a"}
	for _, v := range gitenv.Vars {
		env = append(env, v+"=/x")
	}
	got := strings.Join(battery.Isolated(env), " ")
	if got != "HOME=/h GIT_AUTHOR_NAME=a" {
		t.Fatalf("Isolated = %q", got)
	}
}
