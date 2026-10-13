// Package update brings an installed SE checkout to the newest main and rebuilds se.
package update

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Result says what an update did.
type Result struct {
	From  string `json:"from"`
	To    string `json:"to"`
	Built string `json:"built"`
}

// Run pulls main into repo and builds se to out. It refuses a checkout that is
// not on a clean main, since that holds work an update would pull under.
func Run(repo, out string) (Result, error) {
	var r Result
	branch, err := git(repo, "rev-parse", "--abbrev-ref", "HEAD")
	if err != nil {
		return r, err
	}
	if branch != "main" {
		return r, fmt.Errorf("%s is on %s, not main; the installed SE updates from main alone", repo, branch)
	}
	dirty, err := git(repo, "status", "--porcelain", "--untracked-files=no")
	if err != nil {
		return r, err
	}
	if dirty != "" {
		return r, fmt.Errorf("%s holds uncommitted changes; commit or drop them first", repo)
	}
	if r.From, err = git(repo, "rev-parse", "--short", "HEAD"); err != nil {
		return r, err
	}
	if _, err := git(repo, "pull", "--ff-only", "origin", "main"); err != nil {
		return r, err
	}
	if r.To, err = git(repo, "rev-parse", "--short", "HEAD"); err != nil {
		return r, err
	}
	if err := Build(repo, out); err != nil {
		return r, err
	}
	r.Built = out
	return r, nil
}

// Build compiles se from repo to out, replacing the old binary only once the new one stands.
func Build(repo, out string) error {
	if err := os.MkdirAll(filepath.Dir(out), 0o755); err != nil {
		return err
	}
	// Two starts may build at once; each builds to a file of its own.
	fresh := fmt.Sprintf("%s.%d.new", out, os.Getpid())
	cmd := exec.Command("go", "build", "-o", fresh, "./cmd/se")
	cmd.Dir = repo
	if said, err := cmd.CombinedOutput(); err != nil {
		os.Remove(fresh)
		return fmt.Errorf("go build: %v\n%s", err, said)
	}
	// A running binary cannot be overwritten on Windows, but it can be renamed away.
	old := out + ".old"
	os.Remove(old)
	if _, err := os.Stat(out); err == nil {
		if err := os.Rename(out, old); err != nil {
			return err
		}
	}
	return os.Rename(fresh, out)
}

// Module is the module path an SE checkout's go.mod declares.
const Module = "github.com/mb-89/SE"

// IsCheckout says whether dir is an SE checkout: its go.mod declares SE's module.
func IsCheckout(dir string) bool {
	data, err := os.ReadFile(filepath.Join(dir, "go.mod"))
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

func git(repo string, args ...string) (string, error) {
	cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("git %s: %v: %s", strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return strings.TrimSpace(string(out)), nil
}
