package update

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func repo(t *testing.T, branch string) string {
	t.Helper()
	dir := t.TempDir()
	run(t, dir, "init", "-q", "-b", branch)
	commit(t, dir, "start")
	return dir
}

func run(t *testing.T, dir string, args ...string) string {
	t.Helper()
	out, err := exec.Command("git", append([]string{"-C", dir}, args...)...).CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v %s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

func commit(t *testing.T, dir, msg string) {
	t.Helper()
	run(t, dir, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", msg)
}

// shallow is a clone at depth 1, as a cloud box's setup script makes it, of an
// origin whose main builds a se and has moved on since.
func shallow(t *testing.T) (origin, clone string) {
	t.Helper()
	origin = repo(t, "main")
	for name, text := range map[string]string{
		"go.mod":         "module github.com/mb-89/SE\n\ngo 1.21\n",
		"cmd/se/main.go": "package main\n\nfunc main() {}\n",
	} {
		path := filepath.Join(origin, name)
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	run(t, origin, "add", ".")
	commit(t, origin, "a se that builds")
	clone = filepath.Join(t.TempDir(), "se")
	if out, err := exec.Command("git", "clone", "-q", "--depth", "1", "file://"+origin, clone).CombinedOutput(); err != nil {
		t.Fatalf("clone: %v %s", err, out)
	}
	commit(t, origin, "newer")
	return origin, clone
}

func TestAShallowCloneIsPulledAndRebuilt(t *testing.T) {
	origin, clone := shallow(t)
	out := filepath.Join(clone, "plugin", "bin", "se")
	r, err := Run(clone, out)
	if err != nil {
		t.Fatal(err)
	}
	if want := run(t, origin, "rev-parse", "--short", "HEAD"); r.To != want || r.From == r.To {
		t.Fatalf("%+v, want To %s", r, want)
	}
	if _, err := os.Stat(out); err != nil || r.Built != out {
		t.Fatalf("se was not rebuilt: %+v %v", r, err)
	}
}

func TestACurrentCheckoutIsNotRebuilt(t *testing.T) {
	origin, clone := shallow(t)
	run(t, clone, "pull", "-q", "--ff-only", "origin", "main")
	out := filepath.Join(clone, "se")
	r, err := Run(clone, out)
	if err != nil || r.From != r.To || r.To != run(t, origin, "rev-parse", "--short", "HEAD") {
		t.Fatalf("%+v %v", r, err)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) || r.Built != "" {
		t.Fatalf("se was built though nothing changed: %+v %v", r, err)
	}
}

func TestAFailedPullIsAnErrorThatTouchedNothing(t *testing.T) {
	origin, clone := shallow(t)
	if err := os.RemoveAll(origin); err != nil {
		t.Fatal(err)
	}
	before := run(t, clone, "rev-parse", "HEAD")
	_, err := Run(clone, filepath.Join(clone, "se"))
	var untouched *Untouched
	if err == nil || errors.As(err, &untouched) {
		t.Fatalf("err = %v", err)
	}
	if run(t, clone, "rev-parse", "HEAD") != before {
		t.Fatal("the checkout moved")
	}
}

func TestAFolderOutsideGitIsLeftAlone(t *testing.T) {
	var untouched *Untouched
	if _, err := Run(t.TempDir(), "se"); !errors.As(err, &untouched) {
		t.Fatalf("err = %v", err)
	}
}

func TestAnUpdateRefusesABranch(t *testing.T) {
	dir := repo(t, "feature")
	_, err := Run(dir, filepath.Join(dir, "se"))
	var untouched *Untouched
	if !errors.As(err, &untouched) || !strings.Contains(err.Error(), "not main") {
		t.Fatalf("err = %v", err)
	}
}

func TestAnUpdateRefusesUncommittedWork(t *testing.T) {
	dir := repo(t, "main")
	if err := os.WriteFile(filepath.Join(dir, "f"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, dir, "add", "f")
	_, err := Run(dir, filepath.Join(dir, "se"))
	var untouched *Untouched
	if !errors.As(err, &untouched) || !strings.Contains(err.Error(), "uncommitted") {
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
