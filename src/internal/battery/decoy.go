package battery

import (
	"crypto/sha256"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mb-89/SE/src/internal/gitenv"
)

// Decoy is a throwaway repository go test runs under: GIT_DIR points at it,
// as it does in a pre-push hook run from a worktree. A test that lets git
// inherit that variable acts on the decoy, and Check sees it changed.
type Decoy struct {
	GitDir string
	before map[string][32]byte
}

// NewDecoy makes the decoy in dir, a repository with one commit, and records
// what it holds.
func NewDecoy(dir string) (*Decoy, error) {
	git := func(args ...string) error {
		cmd := exec.Command("git", append([]string{"-c", "user.name=battery", "-c", "user.email=battery@se", "-c", "commit.gpgsign=false"}, args...)...)
		cmd.Dir = dir
		cmd.Env = Isolated(os.Environ())
		if out, err := cmd.CombinedOutput(); err != nil {
			return fmt.Errorf("git %s: %v: %s", strings.Join(args, " "), err, out)
		}
		return nil
	}
	if err := git("init", "-q", "-b", "decoy"); err != nil {
		return nil, err
	}
	if err := git("commit", "-q", "--allow-empty", "-m", "decoy"); err != nil {
		return nil, err
	}
	d := &Decoy{GitDir: filepath.Join(dir, ".git")}
	var err error
	d.before, err = d.snapshot()
	return d, err
}

// Env is env with git's repository variables replaced by GIT_DIR, the decoy.
func (d *Decoy) Env(env []string) []string {
	return append(Isolated(env), "GIT_DIR="+d.GitDir)
}

// Check fails if anything in the decoy changed since NewDecoy, naming what.
func (d *Decoy) Check() error {
	after, err := d.snapshot()
	if err != nil {
		return err
	}
	var changed []string
	for path, sum := range after {
		if was, ok := d.before[path]; !ok || was != sum {
			changed = append(changed, path)
		}
	}
	for path := range d.before {
		if _, ok := after[path]; !ok {
			changed = append(changed, path)
		}
	}
	if len(changed) == 0 {
		return nil
	}
	sort.Strings(changed)
	if len(changed) > 5 {
		changed = append(changed[:5], fmt.Sprintf("and %d more", len(changed)-5))
	}
	return fmt.Errorf("a test ran git on the repository GIT_DIR names; it changed %s; clear git's variables in the package's TestMain (src/internal/gitenv)", strings.Join(changed, ", "))
}

// snapshot is every file in the decoy's git folder, by path, with its hash.
func (d *Decoy) snapshot() (map[string][32]byte, error) {
	files := map[string][32]byte{}
	err := filepath.WalkDir(d.GitDir, func(path string, e fs.DirEntry, err error) error {
		if err != nil || e.IsDir() {
			return err
		}
		text, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(d.GitDir, path)
		files[filepath.ToSlash(rel)] = sha256.Sum256(text)
		return err
	})
	return files, err
}

// Isolated is env without git's repository variables.
func Isolated(env []string) []string {
	var kept []string
	for _, kv := range env {
		name, _, _ := strings.Cut(kv, "=")
		drop := false
		for _, v := range gitenv.Vars {
			if name == v {
				drop = true
			}
		}
		if !drop {
			kept = append(kept, kv)
		}
	}
	return kept
}
