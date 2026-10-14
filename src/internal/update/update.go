// Package update brings an installed SE checkout to the newest main and rebuilds se.
package update

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/mb-89/SE/src/modules/io/disk"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// Result says what an update did.
type Result struct {
	From  string `json:"from"`
	To    string `json:"to"`
	Built string `json:"built"`
}

// Untouched is the error of an update that left the checkout as it was, since
// it is no clean main: it holds work an update would pull under.
type Untouched struct{ Reason string }

func (u *Untouched) Error() string { return u.Reason }

// Run pulls main into repo and, when that brought anything, builds se to out on d.
// It refuses, with an *Untouched, a checkout that is not on a clean main. A
// shallow clone (git clone --depth 1) updates like a full one. It reads and
// writes on d, runs git on g and go on p.
func Run(d disk.Disk, p proc.Procs, g git.Git, repo, out string) (Result, error) {
	var r Result
	run := func(args ...string) (string, error) { return git.Output(g, repo, args...) }
	if inside, err := run("rev-parse", "--is-inside-work-tree"); err != nil || inside != "true" {
		return r, &Untouched{fmt.Sprintf("%s is no git checkout", repo)}
	}
	branch, err := run("rev-parse", "--abbrev-ref", "HEAD")
	if err != nil {
		return r, err
	}
	if branch != "main" {
		return r, &Untouched{fmt.Sprintf("%s is on %s, not main; the installed SE updates from main alone", repo, branch)}
	}
	dirty, err := run("status", "--porcelain", "--untracked-files=no")
	if err != nil {
		return r, err
	}
	if dirty != "" {
		return r, &Untouched{fmt.Sprintf("%s holds uncommitted changes; commit or drop them first", repo)}
	}
	if r.From, err = run("rev-parse", "--short", "HEAD"); err != nil {
		return r, err
	}
	if _, err := run("pull", "--ff-only", "origin", "main"); err != nil {
		return r, err
	}
	if r.To, err = run("rev-parse", "--short", "HEAD"); err != nil || r.To == r.From {
		return r, err
	}
	if err := Build(d, p, g, repo, out); err != nil {
		return r, err
	}
	r.Built = out
	return r, nil
}

// Build compiles se from repo to out on d, reading its commit on g and
// running go on p, replacing the old binary only once the new one stands.
func Build(d disk.Disk, p proc.Procs, g git.Git, repo, out string) error {
	if err := d.MkdirAll(filepath.Dir(out)); err != nil {
		return err
	}
	// Two starts may build at once; each builds to a file of its own.
	fresh := fmt.Sprintf("%s.%d.new", out, os.Getpid())
	args := []string{"build", "-o", fresh}
	if head, err := Head(g, repo); err == nil {
		args = append(args, "-ldflags", Ldflags(head))
	}
	if said, err := proc.Combined(p, proc.Cmd{Name: "go", Args: append(args, "./cmd/se"), Dir: filepath.Join(repo, ModuleDir)}); err != nil {
		_ = d.Remove(fresh)
		return fmt.Errorf("go build: %v\n%s", err, said)
	}
	// A running binary cannot be overwritten on Windows, but it can be renamed away.
	old := out + ".old"
	_ = d.Remove(old)
	if there, err := d.Exists(out); err == nil && there {
		if err := d.Rename(out, old); err != nil {
			return err
		}
	}
	return d.Rename(fresh, out)
}

// Head is the commit repo is at.
func Head(g git.Git, repo string) (string, error) { return git.Output(g, repo, "rev-parse", "HEAD") }

// Ldflags embeds commit in se as the commit it was built from; every build of
// se passes them (see main.commit).
func Ldflags(commit string) string { return "-X main.commit=" + commit }

// ModuleDir is the folder of an SE checkout that holds its go.mod: every Go
// command runs there, and src/build.sh is the build recipe for the shell.
const ModuleDir = "src"

// Module is the module path an SE checkout's go.mod declares.
const Module = "github.com/mb-89/SE/src"

// IsCheckout says whether dir on d is an SE checkout: its go.mod declares SE's module.
func IsCheckout(d disk.Disk, dir string) bool {
	data, err := d.ReadFile(filepath.Join(dir, ModuleDir, "go.mod"))
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if words := strings.Fields(line); len(words) == 2 && words[0] == "module" {
			return strings.Trim(words[1], `"`) == Module
		}
	}
	return false
}
