package update_test

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/update"
	"github.com/mb-89/SE/src/modules/io/disk"
	"github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// drive is the disk go build writes se to: a process writes it, so no fake stands in.
var drive = disk.Real()

// machine is the real machine the tests of a shallow clone still run go on,
// and repos the real git they run; #137 moves them onto the fakes.
var (
	machine = proc.Real()
	repos   = git.Real(machine, env.Real())
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
		"src/go.mod":         "module github.com/mb-89/SE/src\n\ngo 1.21\n",
		"src/cmd/se/main.go": "package main\n\nfunc main() {}\n",
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
	t.Parallel()
	origin, clone := shallow(t)
	out := filepath.Join(clone, "src", "plugin", "bin", "se")
	r, err := update.Run(drive, machine, repos, clone, out)
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
	t.Parallel()
	origin, clone := shallow(t)
	run(t, clone, "pull", "-q", "--ff-only", "origin", "main")
	out := filepath.Join(clone, "se")
	r, err := update.Run(drive, machine, repos, clone, out)
	if err != nil || r.From != r.To || r.To != run(t, origin, "rev-parse", "--short", "HEAD") {
		t.Fatalf("%+v %v", r, err)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) || r.Built != "" {
		t.Fatalf("se was built though nothing changed: %+v %v", r, err)
	}
}

func TestAFailedPullIsAnErrorThatTouchedNothing(t *testing.T) {
	t.Parallel()
	origin, clone := shallow(t)
	if err := os.RemoveAll(origin); err != nil {
		t.Fatal(err)
	}
	before := run(t, clone, "rev-parse", "HEAD")
	_, err := update.Run(drive, machine, repos, clone, filepath.Join(clone, "se"))
	var untouched *update.Untouched
	if err == nil || errors.As(err, &untouched) {
		t.Fatalf("err = %v", err)
	}
	if run(t, clone, "rev-parse", "HEAD") != before {
		t.Fatal("the checkout moved")
	}
}

// box is a fake machine with git and go on it. Its git holds one checkout,
// dir: on branch, at head, dirty or not, and a pull brings it to pulled. Its
// go builds se as the file -o names.
type box struct {
	dir, branch, head, pulled string
	dirty                     bool
}

func (b *box) git(c proc.Cmd) int {
	if c.Dir != b.dir {
		fmt.Fprintf(c.Stderr, "fatal: not a git repository: %s\n", c.Dir)
		return 128
	}
	switch strings.Join(c.Args, " ") {
	case "rev-parse --is-inside-work-tree":
		fmt.Fprintln(c.Stdout, "true")
	case "rev-parse --abbrev-ref HEAD":
		fmt.Fprintln(c.Stdout, b.branch)
	case "status --porcelain --untracked-files=no":
		if b.dirty {
			fmt.Fprintln(c.Stdout, "M  f")
		}
	case "rev-parse HEAD":
		fmt.Fprintln(c.Stdout, b.head)
	case "rev-parse --short HEAD":
		fmt.Fprintln(c.Stdout, b.head[:7])
	case "pull --ff-only origin main":
		b.head = b.pulled
	default:
		fmt.Fprintf(c.Stderr, "git: this box does not do %s\n", c.Args)
		return 1
	}
	return 0
}

func (b *box) goTool(c proc.Cmd) int {
	if c.Dir != filepath.Join(b.dir, update.ModuleDir) || len(c.Args) < 3 || c.Args[0] != "build" || c.Args[1] != "-o" {
		return 2
	}
	if err := os.WriteFile(c.Args[2], []byte("se "+strings.Join(c.Args, " ")), 0o755); err != nil {
		fmt.Fprintln(c.Stderr, err)
		return 1
	}
	return 0
}

// machine answers a fake machine with the box's go installed.
func (b *box) machine() *proc.Fake {
	m := proc.NewFake()
	m.Install("go", b.goTool)
	return m
}

// repos answers the box's git.
func (b *box) repos() *git.Fake { return git.NewFake(b.git) }

const (
	older = "1111111111111111111111111111111111111111"
	newer = "2222222222222222222222222222222222222222"
)

func TestAnUpdateThatBroughtSomethingBuildsSeFromTheNewHead(t *testing.T) {
	t.Parallel()
	b := &box{dir: t.TempDir(), branch: "main", head: older, pulled: newer}
	out := filepath.Join(b.dir, "bin", "se")
	r, err := update.Run(drive, b.machine(), b.repos(), b.dir, out)
	if err != nil || r.From != older[:7] || r.To != newer[:7] || r.Built != out {
		t.Fatalf("%+v %v", r, err)
	}
	built, err := os.ReadFile(out)
	if err != nil || !strings.Contains(string(built), update.Ldflags(newer)) || !strings.HasSuffix(string(built), "./cmd/se") {
		t.Fatalf("se was built as %q (%v)", built, err)
	}
}

func TestAnUpdateThatBroughtNothingBuildsNothing(t *testing.T) {
	t.Parallel()
	b := &box{dir: t.TempDir(), branch: "main", head: older, pulled: older}
	m := b.machine()
	r, err := update.Run(drive, m, b.repos(), b.dir, filepath.Join(b.dir, "se"))
	if err != nil || r.From != r.To || r.Built != "" {
		t.Fatalf("%+v %v", r, err)
	}
	for _, line := range m.Lines() {
		if strings.HasPrefix(line, "go ") {
			t.Fatalf("se was built though nothing changed: %s", line)
		}
	}
}

func TestAFolderOutsideGitIsLeftAlone(t *testing.T) {
	t.Parallel()
	b := &box{dir: t.TempDir(), branch: "main", head: older, pulled: newer}
	var untouched *update.Untouched
	if _, err := update.Run(drive, b.machine(), b.repos(), t.TempDir(), "se"); !errors.As(err, &untouched) {
		t.Fatalf("err = %v", err)
	}
}

func TestAnUpdateRefusesABranch(t *testing.T) {
	t.Parallel()
	b := &box{dir: t.TempDir(), branch: "feature", head: older, pulled: newer}
	_, err := update.Run(drive, b.machine(), b.repos(), b.dir, filepath.Join(b.dir, "se"))
	var untouched *update.Untouched
	if !errors.As(err, &untouched) || !strings.Contains(err.Error(), "not main") || b.head != older {
		t.Fatalf("err = %v, at %s", err, b.head)
	}
}

func TestAnUpdateRefusesUncommittedWork(t *testing.T) {
	t.Parallel()
	b := &box{dir: t.TempDir(), branch: "main", head: older, pulled: newer, dirty: true}
	_, err := update.Run(drive, b.machine(), b.repos(), b.dir, filepath.Join(b.dir, "se"))
	var untouched *update.Untouched
	if !errors.As(err, &untouched) || !strings.Contains(err.Error(), "uncommitted") || b.head != older {
		t.Fatalf("err = %v, at %s", err, b.head)
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
