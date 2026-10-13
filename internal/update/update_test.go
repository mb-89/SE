package update

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func repo(t *testing.T, branch string) string {
	t.Helper()
	dir := t.TempDir()
	for _, args := range [][]string{
		{"init", "-q", "-b", branch},
		{"-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "start"},
	} {
		cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	return dir
}

func TestAnUpdateRefusesABranch(t *testing.T) {
	dir := repo(t, "feature")
	_, err := Run(dir, filepath.Join(dir, "se"))
	if err == nil || !strings.Contains(err.Error(), "not main") {
		t.Fatalf("err = %v", err)
	}
}

func TestAnUpdateRefusesUncommittedWork(t *testing.T) {
	dir := repo(t, "main")
	if err := os.WriteFile(filepath.Join(dir, "f"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"add", "f"}} {
		if out, err := exec.Command("git", append([]string{"-C", dir}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("%v %s", err, out)
		}
	}
	_, err := Run(dir, filepath.Join(dir, "se"))
	if err == nil || !strings.Contains(err.Error(), "uncommitted") {
		t.Fatalf("err = %v", err)
	}
}
