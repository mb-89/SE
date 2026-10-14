package battery

import (
	"fmt"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// The battery records the tree it passed in one file of the checkout, which
// se issue land and se issue keep commit with the work: the git tree of HEAD
// with that file left out, so recording the pass does not change what it
// names. CI's se fleet trust computes the same tree of the commit it checked
// out and runs the battery only where the file names another (Trusted).

// Instance is the wiring's instance of Module.
const Instance = "battery"

// PassedFile is the built-in value of Module's passed key: the file, from the
// checkout's top, that names the tree the battery passed.
const PassedFile = "tests/passed"

// Module declares the battery's config on the index: where it records the
// tree it passed.
var Module = index.Declare("battery", "The battery, tests/check.sh: what it records of a pass, which CI trusts.",
	index.Config("passed", PassedFile, "The file, from the checkout's top, that names the tree the battery passed: HEAD's git tree with this file left out. se issue land and se issue keep commit it with the work, and CI's se fleet trust skips the battery where it names the tree CI checked out."),
)

func init() { index.Register(Module) }

// Passed answers Module's passed key as the wiring se carries gives it.
func Passed() (string, error) {
	w, err := index.Wired()
	if err != nil {
		return "", err
	}
	own := index.Wiring{}
	for _, in := range w.Instances {
		if in.Module == Module.Name() {
			own.Instances = append(own.Instances, in)
		}
	}
	ix, err := index.Start(own, Module)
	if err != nil {
		return "", err
	}
	name := Instance + "/" + index.ConfigPrefix + "passed"
	v, err := ix.Read(name)
	if err != nil {
		return "", err
	}
	p, ok := v.V.(string)
	if !ok || p == "" || strings.HasPrefix(p, "/") || strings.Contains("/"+p+"/", "/../") {
		return "", fmt.Errorf("%s names no file inside the checkout: %v", name, v.V)
	}
	return p, nil
}

// treeHash is what git names a tree by.
var treeHash = regexp.MustCompile(`^[0-9a-f]{40,64}$`)

// git runs git in top and answers what it printed.
func git(procs proc.Procs, top string, stdin string, args ...string) (string, error) {
	c := proc.Cmd{Name: "git", Args: args, Dir: top}
	if stdin != "" {
		c.Stdin = strings.NewReader(stdin)
	}
	return proc.Output(procs, c)
}

// Dirty answers git status --porcelain of the worktree at top, the passed
// file left out: the battery rewrites that file, and it names no code.
func Dirty(procs proc.Procs, top string) (string, error) {
	file, err := Passed()
	if err != nil {
		return "", err
	}
	return git(procs, top, "", "status", "--porcelain", "--", ":(exclude)"+file)
}

// TreeOf answers the git tree of rev in the repository at top with the
// passed file left out, as git leaves out a folder that holds nothing else:
// what the battery records, and what CI compares the record with.
func TreeOf(procs proc.Procs, top, rev string) (string, error) {
	file, err := Passed()
	if err != nil {
		return "", err
	}
	tree, empty, err := without(procs, top, rev+"^{tree}", strings.Split(file, "/"))
	if err == nil && empty {
		// git's empty tree, in whichever hash the repository names by.
		return git(procs, top, "", "mktree")
	}
	return tree, err
}

// without answers tree with the entry at path left out, and empty where
// nothing else is left in it. It writes the trees it makes with git mktree,
// which names a tree by its entries alone.
func without(procs proc.Procs, top, tree string, path []string) (string, bool, error) {
	listed, err := git(procs, top, "", "ls-tree", "-z", tree)
	if err != nil {
		return "", false, err
	}
	var kept []string
	for _, e := range strings.Split(listed, "\x00") {
		meta, name, ok := strings.Cut(e, "\t")
		if !ok {
			continue
		}
		if name != path[0] {
			kept = append(kept, e)
			continue
		}
		f := strings.Fields(meta) // mode, type, object
		if len(path) == 1 {
			continue
		}
		if len(f) != 3 || f[1] != "tree" {
			kept = append(kept, e)
			continue
		}
		sub, empty, err := without(procs, top, f[2], path[1:])
		if err != nil {
			return "", false, err
		}
		if !empty {
			kept = append(kept, f[0]+" tree "+sub+"\t"+name)
		}
	}
	if len(kept) == 0 {
		return "", true, nil
	}
	made, err := git(procs, top, strings.Join(kept, "\x00")+"\x00", "mktree", "-z")
	return made, false, err
}

// Tree answers TreeOf HEAD of the worktree at top, or "" where it has changes
// not committed beside the passed file: a dirty worktree is not the tree its
// HEAD names.
func Tree(procs proc.Procs, top string) (string, error) {
	dirty, err := Dirty(procs, top)
	if err != nil || dirty != "" {
		return "", err
	}
	return TreeOf(procs, top, "HEAD")
}

// Pass records started as the tree the battery passed at top, in the passed
// file, where the worktree still holds it, clean: a commit made or a file
// changed while the battery ran is not what it checked. It records nothing
// where started is "" (the battery started on a dirty worktree), and says so.
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
	file, err := Passed()
	if err != nil {
		return "", err
	}
	at := filepath.Join(top, filepath.FromSlash(file))
	if err := d.MkdirAll(filepath.Dir(at)); err != nil {
		return "", err
	}
	if err := d.WriteFile(at, []byte(started+"\n")); err != nil {
		return "", err
	}
	return "the battery passed tree " + started, nil
}

// Recorded answers the tree the passed file names in rev of the repository
// at top, or in its index where rev is ""; ok is false where rev holds no
// passed file.
func Recorded(procs proc.Procs, top, rev string) (tree string, ok bool, err error) {
	file, err := Passed()
	if err != nil {
		return "", false, err
	}
	obj, ok, err := object(procs, top, rev, file)
	if err != nil || !ok {
		return "", false, err
	}
	data, err := git(procs, top, "", "cat-file", "blob", obj)
	if err != nil {
		return "", false, err
	}
	if !treeHash.MatchString(data) {
		return "", false, fmt.Errorf("%s names no tree: %q", file, data)
	}
	return data, true, nil
}

// object answers the object file names in rev at top, or in its index where
// rev is ""; ok is false where there is none.
func object(procs proc.Procs, top, rev, file string) (obj string, ok bool, err error) {
	obj, err = git(procs, top, "", "rev-parse", "--verify", "--quiet", rev+":"+file)
	if code, exited := proc.ExitCode(err); exited && code == 1 {
		return "", false, nil
	}
	return obj, err == nil, err
}

// Stage puts the passed file of the worktree at top, as the battery left it,
// into the index, and answers the tree it names there; ok is false where
// there is none.
func Stage(procs proc.Procs, top string) (tree string, ok bool, err error) {
	file, err := Passed()
	if err != nil {
		return "", false, err
	}
	changed, err := git(procs, top, "", "status", "--porcelain", "--", file)
	if err != nil {
		return "", false, err
	}
	if changed != "" {
		if _, err := git(procs, top, "", "add", "-A", "--", file); err != nil {
			return "", false, err
		}
	}
	return Recorded(procs, top, "")
}

// CommitSubject starts the subject of the commit that records a pass, which
// names the tree; the landing facts count no such commit as work.
const CommitSubject = "The battery passed tree "

// Commit commits the passed file staged at top, where it differs from
// HEAD's, naming tree: the pushed commit holds the record of its pass.
func Commit(procs proc.Procs, top, tree string) error {
	file, err := Passed()
	if err != nil {
		return err
	}
	_, err = git(procs, top, "", "diff", "--cached", "--quiet", "--", file)
	if code, exited := proc.ExitCode(err); !exited || code != 1 {
		return err
	}
	_, err = git(procs, top, "", "commit", "-q", "-m", CommitSubject+tree, "--", file)
	return err
}

// Reset puts the passed file at top back as HEAD holds it, or takes it away
// where HEAD holds none, before a merge: a battery's record left in the
// worktree would stop the merge, and the battery runs again after it.
func Reset(procs proc.Procs, top string) error {
	file, err := Passed()
	if err != nil {
		return err
	}
	if _, ok, err := object(procs, top, "HEAD", file); err != nil || ok {
		if err == nil {
			_, err = git(procs, top, "", "checkout", "-q", "HEAD", "--", file)
		}
		return err
	}
	if _, err := git(procs, top, "", "rm", "-q", "--cached", "--ignore-unmatch", "--", file); err != nil {
		return err
	}
	_, err = git(procs, top, "", "clean", "-q", "-f", "--", file)
	return err
}

// Resolve settles a merge at top that conflicts in the passed file alone,
// taking the branch's own, since the battery runs again on the merge and
// writes it anew; resolved is false, and nothing is touched, where any other
// path conflicts.
func Resolve(procs proc.Procs, top string) (resolved bool, err error) {
	file, err := Passed()
	if err != nil {
		return false, err
	}
	unmerged, err := git(procs, top, "", "diff", "--name-only", "--diff-filter=U")
	if err != nil || unmerged != file {
		return false, err
	}
	if _, err := git(procs, top, "", "checkout", "-q", "--ours", "--", file); err != nil {
		// The branch had taken it away: so does the merge.
		_, err = git(procs, top, "", "rm", "-q", "--", file)
		return err == nil, err
	}
	_, err = git(procs, top, "", "add", "--", file)
	return err == nil, err
}

// Trusted says why CI may skip the battery on rev of the checkout at top:
// rev's passed file names rev's tree with it left out, so the battery passed
// that very tree. Where it may not (no file, or one naming another tree, as
// where main moved since), the error says why, and CI runs the battery. It is
// trust in one's own boxes: faking the file is sabotage, not an accident.
func Trusted(procs proc.Procs, top, rev string) (string, error) {
	file, err := Passed()
	if err != nil {
		return "", err
	}
	tree, err := TreeOf(procs, top, rev)
	if err != nil {
		return "", err
	}
	passed, ok, err := Recorded(procs, top, rev)
	switch {
	case err != nil:
		return "", err
	case !ok:
		return "", fmt.Errorf("%s holds no %s: no battery recorded a pass", rev, file)
	case passed != tree:
		return "", fmt.Errorf("%s's %s names tree %s, and its tree without it is %s: the battery passed other code", rev, file, passed, tree)
	}
	return fmt.Sprintf("%s's %s names its tree %s: the battery passed it", rev, file, tree), nil
}
