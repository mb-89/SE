package battery

import (
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// TreeFile, in Dir, names the git tree the battery passed: HEAD^{tree} of a
// clean worktree, the same when the battery started as when it passed. A
// battery run is bound to the exact code it ran over, so se issue land pushes
// only a tree the battery passed.
const TreeFile = "tree"

// treeHash is what git names a tree by.
var treeHash = regexp.MustCompile(`^[0-9a-f]{40,64}$`)

// Tree answers HEAD^{tree} of the worktree at top, or "" where it has changes
// not committed: a dirty worktree is not the tree its HEAD names.
func Tree(procs proc.Procs, top string) (string, error) {
	dirty, err := proc.Output(procs, proc.Cmd{Name: "git", Args: []string{"status", "--porcelain"}, Dir: top})
	if err != nil || dirty != "" {
		return "", err
	}
	return proc.Output(procs, proc.Cmd{Name: "git", Args: []string{"rev-parse", "HEAD^{tree}"}, Dir: top})
}

// Pass records started as the tree the battery passed at top, where the
// worktree still holds it, clean: a commit made or a file changed while the
// battery ran is not what it checked. It records nothing where started is ""
// (the battery started on a dirty worktree), and says so.
func Pass(d disk.Disk, procs proc.Procs, top, started string) (string, error) {
	if started == "" {
		return "the worktree had changes not committed when the battery started, so it records no tree", nil
	}
	now, err := Tree(procs, top)
	if err != nil {
		return "", err
	}
	if now != started {
		return fmt.Sprintf("the worktree moved from tree %s while the battery ran, so it records no tree", started), nil
	}
	if err := d.MkdirAll(filepath.Join(top, Dir)); err != nil {
		return "", err
	}
	if err := d.WriteFile(filepath.Join(top, Dir, TreeFile), []byte(started+"\n")); err != nil {
		return "", err
	}
	return "the battery passed tree " + started, nil
}

// Passed answers the tree the last battery run at top on d passed; ok is
// false where it passed none.
func Passed(d disk.Disk, top string) (tree string, ok bool, err error) {
	data, err := d.ReadFile(filepath.Join(top, Dir, TreeFile))
	if errors.Is(err, fs.ErrNotExist) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	tree = strings.TrimSpace(string(data))
	if !treeHash.MatchString(tree) {
		return "", false, fmt.Errorf("%s names no tree: %q", TreeFile, tree)
	}
	return tree, true, nil
}
