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

func TestACheckoutIsKnownByItsModule(t *testing.T) {
	for mod, want := range map[string]bool{
		"module github.com/mb-89/SE\n\ngo 1.24\n": true,
		"// SE\nmodule \"github.com/mb-89/SE\"\n": true,
		"module github.com/mb-89/SE/sub\n":        false,
		"module example.com/other\n":              false,
	} {
		dir := t.TempDir()
		if err := os.WriteFile(filepath.Join(dir, "go.mod"), []byte(mod), 0o644); err != nil {
			t.Fatal(err)
		}
		if got := IsCheckout(dir); got != want {
			t.Errorf("%q: %v, want %v", mod, got, want)
		}
	}
	if IsCheckout(t.TempDir()) {
		t.Error("a folder without go.mod is a checkout")
	}
}
