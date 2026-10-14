package update_test

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/update"
)

// box is a fake machine with git and go on it, both working on its disk. Its
// go builds se as the file -o names, holding the words it was run with.
type box struct {
	disk *disk.Fake
	proc *proc.Fake
	t    *testing.T
}

func newBox(t *testing.T) *box {
	b := &box{disk: disk.NewFake(), proc: proc.NewFake(), t: t}
	b.proc.InstallGit(b.disk)
	b.proc.Install("go", func(c proc.Cmd) int {
		if len(c.Args) < 3 || c.Args[0] != "build" || c.Args[1] != "-o" {
			return 2
		}
		if there, _ := b.disk.Exists(filepath.Join(c.Dir, "go.mod")); !there {
			fmt.Fprintln(c.Stderr, "go: cannot find main module")
			return 1
		}
		if err := b.disk.WriteFile(c.Args[2], []byte("se "+strings.Join(c.Args, " "))); err != nil {
			fmt.Fprintln(c.Stderr, err)
			return 1
		}
		return 0
	})
	return b
}

// git runs git in dir on the box, and answers what it printed, trimmed.
func (b *box) git(dir string, args ...string) string {
	b.t.Helper()
	out, err := proc.Output(b.proc, proc.Cmd{Name: "git", Args: args, Dir: dir})
	if err != nil {
		b.t.Fatal(err)
	}
	return out
}

// write puts text at the file name in dir.
func (b *box) write(dir, name, text string) {
	b.t.Helper()
	p := filepath.Join(dir, filepath.FromSlash(name))
	if err := b.disk.MkdirAll(filepath.Dir(p)); err != nil {
		b.t.Fatal(err)
	}
	if err := b.disk.WriteFile(p, []byte(text)); err != nil {
		b.t.Fatal(err)
	}
}

func (b *box) commit(dir, msg string) { b.git(dir, "commit", "-q", "--allow-empty", "-m", msg) }

// shallow is a clone at depth 1 on branch, as a cloud box's setup script makes
// it, of an origin whose main builds a se and has moved on since.
func (b *box) shallow(branch string) (origin, clone string) {
	b.t.Helper()
	origin, clone = filepath.FromSlash("/origin"), filepath.FromSlash("/se")
	b.git("/", "init", "-q", "-b", "main", origin)
	b.write(origin, "src/go.mod", "module github.com/mb-89/SE/src\n\ngo 1.21\n")
	b.write(origin, "src/cmd/se/main.go", "package main\n\nfunc main() {}\n")
	b.git(origin, "add", ".")
	b.commit(origin, "a se that builds")
	b.git("/", "clone", "-q", "--depth", "1", "file://"+origin, clone)
	if branch != "main" {
		b.git(clone, "checkout", "-q", "-b", branch)
	}
	b.commit(origin, "newer")
	return origin, clone
}

func TestAShallowCloneIsPulledAndRebuiltFromTheNewHead(t *testing.T) {
	t.Parallel()
	b := newBox(t)
	origin, clone := b.shallow("main")
	out := filepath.Join(clone, "src", "plugin", "bin", "se")
	r, err := update.Run(b.disk, b.proc, clone, out)
	if err != nil {
		t.Fatal(err)
	}
	if want := b.git(origin, "rev-parse", "--short", "HEAD"); r.To != want || r.From == r.To || r.Built != out {
		t.Fatalf("%+v, want To %s", r, want)
	}
	built, err := b.disk.ReadFile(out)
	if err != nil || !strings.Contains(string(built), update.Ldflags(b.git(origin, "rev-parse", "HEAD"))) || !strings.HasSuffix(string(built), "./cmd/se") {
		t.Fatalf("se was built as %q (%v)", built, err)
	}
}

func TestACurrentCheckoutIsNotRebuilt(t *testing.T) {
	t.Parallel()
	b := newBox(t)
	origin, clone := b.shallow("main")
	b.git(clone, "pull", "-q", "--ff-only", "origin", "main")
	out := filepath.Join(clone, "se")
	r, err := update.Run(b.disk, b.proc, clone, out)
	if err != nil || r.From != r.To || r.To != b.git(origin, "rev-parse", "--short", "HEAD") || r.Built != "" {
		t.Fatalf("%+v %v", r, err)
	}
	for _, line := range b.proc.Lines() {
		if strings.HasPrefix(line, "go ") {
			t.Fatalf("se was built though nothing changed: %s", line)
		}
	}
}

func TestAFailedPullIsAnErrorThatTouchedNothing(t *testing.T) {
	t.Parallel()
	b := newBox(t)
	origin, clone := b.shallow("main")
	if err := b.disk.RemoveAll(origin); err != nil {
		t.Fatal(err)
	}
	before := b.git(clone, "rev-parse", "HEAD")
	_, err := update.Run(b.disk, b.proc, clone, filepath.Join(clone, "se"))
	var untouched *update.Untouched
	if err == nil || errors.As(err, &untouched) {
		t.Fatalf("err = %v", err)
	}
	if b.git(clone, "rev-parse", "HEAD") != before {
		t.Fatal("the checkout moved")
	}
}

func TestAFolderOutsideGitIsLeftAlone(t *testing.T) {
	t.Parallel()
	b := newBox(t)
	b.shallow("main")
	if err := b.disk.MkdirAll(filepath.FromSlash("/plain")); err != nil {
		t.Fatal(err)
	}
	var untouched *update.Untouched
	if _, err := update.Run(b.disk, b.proc, filepath.FromSlash("/plain"), "se"); !errors.As(err, &untouched) {
		t.Fatalf("err = %v", err)
	}
}

func TestAnUpdateRefusesABranch(t *testing.T) {
	t.Parallel()
	b := newBox(t)
	_, clone := b.shallow("feature")
	head := b.git(clone, "rev-parse", "HEAD")
	_, err := update.Run(b.disk, b.proc, clone, filepath.Join(clone, "se"))
	var untouched *update.Untouched
	if !errors.As(err, &untouched) || !strings.Contains(err.Error(), "not main") || b.git(clone, "rev-parse", "HEAD") != head {
		t.Fatalf("err = %v", err)
	}
}

func TestAnUpdateRefusesUncommittedWork(t *testing.T) {
	t.Parallel()
	b := newBox(t)
	_, clone := b.shallow("main")
	b.write(clone, "src/go.mod", "module changed\n")
	head := b.git(clone, "rev-parse", "HEAD")
	_, err := update.Run(b.disk, b.proc, clone, filepath.Join(clone, "se"))
	var untouched *update.Untouched
	if !errors.As(err, &untouched) || !strings.Contains(err.Error(), "uncommitted") || b.git(clone, "rev-parse", "HEAD") != head {
		t.Fatalf("err = %v", err)
	}
}

func TestACheckoutIsKnownByItsModule(t *testing.T) {
	t.Parallel()
	for mod, want := range map[string]bool{
		"module github.com/mb-89/SE/src\n\ngo 1.24\n": true,
		"// SE\nmodule \"github.com/mb-89/SE/src\"\n": true,
		"module github.com/mb-89/SE\n":                false,
		"module example.com/other\n":                  false,
	} {
		d, dir := disk.NewFake(), filepath.FromSlash("/se")
		if err := d.MkdirAll(filepath.Join(dir, update.ModuleDir)); err != nil {
			t.Fatal(err)
		}
		if err := d.WriteFile(filepath.Join(dir, update.ModuleDir, "go.mod"), []byte(mod)); err != nil {
			t.Fatal(err)
		}
		if got := update.IsCheckout(d, dir); got != want {
			t.Errorf("%q: %v, want %v", mod, got, want)
		}
	}
	if update.IsCheckout(disk.NewFake(), filepath.FromSlash("/se")) {
		t.Error("a folder without go.mod is a checkout")
	}
}
