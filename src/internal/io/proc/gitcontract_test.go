package proc_test

import (
	"bytes"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// gitOn is a machine with git on it, the disk its work trees stand on and a
// folder to make repositories in.
type gitOn struct {
	procs proc.Procs
	disk  disk.Disk
	root  string
}

// git runs git in dir as whoever commits, and answers what it printed to
// stdout, trimmed, and its exit code.
func (m gitOn) git(t *testing.T, dir string, args ...string) (string, int) {
	t.Helper()
	var out, errs bytes.Buffer
	c := proc.Cmd{Name: "git", Args: append([]string{"-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"}, args...), Dir: dir, Stdout: &out, Stderr: &errs}
	err := m.procs.Run(c)
	code, ok := proc.ExitCode(err)
	if !ok {
		t.Fatalf("git %v: %v", args, err)
	}
	return strings.TrimSpace(out.String()), code
}

// must runs git as git does, and fails the test where it does not exit 0.
func (m gitOn) must(t *testing.T, dir string, args ...string) string {
	t.Helper()
	out, code := m.git(t, dir, args...)
	if code != 0 {
		t.Fatalf("git %v in %s: exit %d, %q", args, dir, code, out)
	}
	return out
}

// write puts text at the file name in dir.
func (m gitOn) write(t *testing.T, dir, name, text string) {
	t.Helper()
	p := filepath.Join(dir, filepath.FromSlash(name))
	if err := m.disk.MkdirAll(filepath.Dir(p)); err != nil {
		t.Fatal(err)
	}
	if err := m.disk.WriteFile(p, []byte(text)); err != nil {
		t.Fatal(err)
	}
}

// commit commits name holding text in dir.
func (m gitOn) commit(t *testing.T, dir, name, text string) {
	t.Helper()
	m.write(t, dir, name, text)
	m.must(t, dir, "add", name)
	m.must(t, dir, "commit", "-q", "-m", name)
}

// boxes is a bare origin with a main of one commit, and two clones of it.
func (m gitOn) boxes(t *testing.T) (origin, a, b string) {
	t.Helper()
	origin, a, b = filepath.Join(m.root, "origin.git"), filepath.Join(m.root, "a"), filepath.Join(m.root, "b")
	m.must(t, m.root, "init", "-q", "--bare", "-b", "main", origin)
	m.must(t, m.root, "clone", "-q", origin, a)
	m.must(t, a, "checkout", "-q", "-b", "main")
	m.commit(t, a, "start", "start\n")
	m.must(t, a, "push", "-q", "origin", "main")
	m.must(t, m.root, "clone", "-q", origin, b)
	return origin, a, b
}

// gitContract is the one suite every git keeps, the fake as the real one.
// fresh answers a new machine with git on it for each case; the cases run in
// parallel.
func gitContract(t *testing.T, fresh func(t *testing.T) gitOn) {
	t.Run("a clone pushes its commits, and another clone sees them", func(t *testing.T) {
		t.Parallel()
		m := fresh(t)
		origin, a, b := m.boxes(t)
		if got, want := m.must(t, origin, "rev-parse", "main"), m.must(t, a, "rev-parse", "HEAD"); got != want {
			t.Fatalf("origin's main is %s, a is at %s", got, want)
		}
		for dir, want := range map[string]string{
			a: "main", b: "main",
		} {
			if got := m.must(t, dir, "rev-parse", "--abbrev-ref", "HEAD"); got != want {
				t.Errorf("%s is on %s", dir, got)
			}
			if got := m.must(t, dir, "rev-parse", "--abbrev-ref", "@{upstream}"); got != "origin/main" {
				t.Errorf("%s tracks %s", dir, got)
			}
		}
		if got := m.must(t, b, "log", "-1", "--format=%s"); got != "start" {
			t.Fatalf("b's last commit says %q", got)
		}
		if data, err := m.disk.ReadFile(filepath.Join(b, "start")); err != nil || string(data) != "start\n" {
			t.Fatalf("b holds %q, %v", data, err)
		}
		if got := m.must(t, b, "remote", "get-url", "origin"); got != origin {
			t.Fatalf("b's origin is %s", got)
		}
		if got := m.must(t, a, "rev-parse", "--is-inside-work-tree"); got != "true" {
			t.Fatalf("a is inside a work tree: %s", got)
		}
		if short, full := m.must(t, a, "rev-parse", "--short", "HEAD"), m.must(t, a, "rev-parse", "HEAD"); len(short) < 7 || !strings.HasPrefix(full, short) {
			t.Fatalf("short %s of %s", short, full)
		}
		full := m.must(t, a, "rev-parse", "HEAD")
		if got := m.must(t, a, "rev-parse", "--verify", "--quiet", full[:8]+"^{commit}"); got != full {
			t.Fatalf("%s^{commit} verifies as %q", full[:8], got)
		}
		if out, code := m.git(t, a, "rev-parse", "--verify", "--quiet", strings.Repeat("e", 40)+"^{commit}"); code != 1 || out != "" {
			t.Fatalf("an unknown commit verifies: exit %d, %q", code, out)
		}
		m.commit(t, a, "later", "later\n")
		if _, code := m.git(t, a, "merge-base", "--is-ancestor", full, "HEAD"); code != 0 {
			t.Fatalf("HEAD~1 is no ancestor of HEAD: exit %d", code)
		}
		if _, code := m.git(t, a, "merge-base", "--is-ancestor", "HEAD", "origin/main"); code != 1 {
			t.Fatalf("a commit not pushed is an ancestor of origin/main: exit %d", code)
		}
		outside := filepath.Join(m.root, "plain")
		if err := m.disk.MkdirAll(outside); err != nil {
			t.Fatal(err)
		}
		if _, code := m.git(t, outside, "rev-parse", "--is-inside-work-tree"); code != 128 {
			t.Fatalf("a plain folder answered exit %d", code)
		}
		if _, code := m.git(t, a, "remote", "get-url", "upstream"); code != 2 {
			t.Fatalf("a remote that is not there answered exit %d", code)
		}
	})
	t.Run("a push creates a branch only where none is, under a lease", func(t *testing.T) {
		t.Parallel()
		m := fresh(t)
		origin, a, b := m.boxes(t)
		stake := func(dir string) (string, int) {
			m.must(t, dir, "fetch", "-q", "origin", "main")
			return m.git(t, dir, "push", "--porcelain", "--force-with-lease=refs/heads/issue-5:", "origin", "refs/remotes/origin/main:refs/heads/issue-5")
		}
		if said, code := stake(a); code != 0 || !strings.Contains("\n"+said, "\n*\t") {
			t.Fatalf("the first push: exit %d, %q", code, said)
		}
		// The same commit again is no update at all.
		if said, code := stake(a); code != 0 || strings.Contains("\n"+said, "\n*\t") {
			t.Fatalf("the same push again: exit %d, %q", code, said)
		}
		m.commit(t, a, "more", "more\n")
		m.must(t, a, "push", "-q", "origin", "HEAD:main")
		if said, code := stake(b); code == 0 || strings.Contains("\n"+said, "\n*\t") {
			t.Fatalf("the push over a branch there: exit %d, %q", code, said)
		}
		if got, want := m.must(t, origin, "rev-parse", "issue-5"), m.must(t, origin, "rev-parse", "main~1"); got != want {
			t.Fatalf("issue-5 moved to %s, want %s", got, want)
		}
		if _, code := m.git(t, b, "ls-remote", "--exit-code", "origin", "refs/heads/issue-5"); code != 0 {
			t.Fatalf("ls-remote of a branch there: exit %d", code)
		}
		if _, code := m.git(t, b, "ls-remote", "--exit-code", "origin", "refs/heads/issue-9"); code != 2 {
			t.Fatalf("ls-remote of no branch: exit %d", code)
		}
		m.must(t, b, "fetch", "-q", "origin", "+refs/heads/issue-5:refs/remotes/origin/issue-5")
		m.must(t, b, "checkout", "-q", "-b", "issue-5", "--track", "origin/issue-5")
		if got := m.must(t, b, "rev-parse", "--abbrev-ref", "@{upstream}"); got != "origin/issue-5" {
			t.Fatalf("b tracks %s", got)
		}
		m.must(t, b, "checkout", "-q", "main")
		m.must(t, b, "branch", "-q", "-D", "issue-5")
		if got := m.must(t, b, "branch", "--list", "issue-5"); got != "" {
			t.Fatalf("issue-5 stands in b: %q", got)
		}
		m.must(t, a, "push", "-q", "origin", "--delete", "issue-5")
		if got := m.must(t, origin, "branch", "--list", "issue-5"); got != "" {
			t.Fatalf("issue-5 stands on origin: %q", got)
		}
		if _, code := m.git(t, a, "push", "-q", "origin", "--delete", "issue-5"); code == 0 {
			t.Fatal("a branch deleted twice")
		}
		if _, code := m.git(t, a, "fetch", "-q", "origin", "refs/heads/issue-5:refs/remotes/origin/issue-5"); code != 128 {
			t.Fatalf("a fetch of no branch: exit %d", code)
		}
	})
	t.Run("a push that would lose commits is refused", func(t *testing.T) {
		t.Parallel()
		m := fresh(t)
		origin, a, b := m.boxes(t)
		m.commit(t, a, "x", "a\n")
		m.must(t, a, "push", "-q", "origin", "main")
		m.commit(t, b, "y", "b\n")
		if _, code := m.git(t, b, "push", "-q", "origin", "main"); code == 0 {
			t.Fatal("a push that loses a's commit went through")
		}
		if got, want := m.must(t, origin, "rev-parse", "main"), m.must(t, a, "rev-parse", "HEAD"); got != want {
			t.Fatalf("origin's main moved to %s", got)
		}
		m.must(t, b, "push", "-q", "origin", "main:issue-7")
		m.must(t, b, "push", "-q", "-u", "origin", "HEAD:refs/heads/issue-8")
		if got := m.must(t, b, "rev-parse", "--abbrev-ref", "@{upstream}"); got != "origin/issue-8" {
			t.Fatalf("b tracks %s after push -u", got)
		}
	})
	t.Run("a merge takes in both sides, and a conflict is undone", func(t *testing.T) {
		t.Parallel()
		m := fresh(t)
		_, a, b := m.boxes(t)
		m.commit(t, a, "x", "a\n")
		m.commit(t, b, "y", "b\n")
		m.must(t, b, "push", "-q", "origin", "main")
		m.must(t, a, "fetch", "-q", "origin", "main")
		m.must(t, a, "merge", "-q", "--no-edit", "origin/main")
		for _, f := range []string{"x", "y", "start"} {
			if there, _ := m.disk.Exists(filepath.Join(a, f)); !there {
				t.Errorf("a lacks %s after the merge", f)
			}
		}
		if got := m.must(t, a, "rev-list", "--count", "--merges", "origin/main..HEAD"); got != "1" {
			t.Errorf("merges %s", got)
		}
		if got := m.must(t, a, "rev-list", "--count", "--no-merges", "origin/main..HEAD"); got != "1" {
			t.Errorf("commits %s", got)
		}
		if out, code := m.git(t, a, "merge", "-q", "--no-edit", "origin/main"); code != 0 || out != "" {
			t.Errorf("a merge of nothing new: exit %d, %q", code, out)
		}
		m.commit(t, a, "z", "a\n")
		m.commit(t, b, "z", "b\n")
		m.must(t, b, "push", "-q", "origin", "main")
		m.must(t, a, "fetch", "-q", "origin")
		head := m.must(t, a, "rev-parse", "HEAD")
		if _, code := m.git(t, a, "merge", "-q", "--no-edit", "origin/main"); code == 0 {
			t.Fatal("a conflict merged")
		}
		if dirty := m.must(t, a, "status", "--porcelain"); !strings.Contains(dirty, "z") {
			t.Fatalf("the conflict shows as %q", dirty)
		}
		m.must(t, a, "merge", "--abort")
		if dirty := m.must(t, a, "status", "--porcelain"); dirty != "" || m.must(t, a, "rev-parse", "HEAD") != head {
			t.Fatalf("the abort left %q", dirty)
		}
		if _, code := m.git(t, a, "merge", "--abort"); code != 128 {
			t.Fatalf("an abort with no merge: exit %d", code)
		}
		m.must(t, b, "checkout", "-q", "-b", "side", "main~1")
		m.must(t, b, "merge", "-q", "--no-ff", "-m", "merge main", "main")
		if got := m.must(t, b, "log", "-1", "--format=%s"); got != "merge main" {
			t.Fatalf("the merge says %q", got)
		}
	})
	t.Run("status, ls-files and check-ignore see what git tracks and ignores", func(t *testing.T) {
		t.Parallel()
		m := fresh(t)
		_, a, _ := m.boxes(t)
		m.commit(t, a, ".gitignore", "bin/\n*.log\n")
		m.write(t, a, "new.md", "new\n")
		m.write(t, a, "x.log", "log\n")
		m.write(t, a, "bin/se", "se\n")
		m.write(t, a, "d/e.md", "e\n")
		m.write(t, a, "start", "changed\n")
		if got, want := m.must(t, a, "status", "--porcelain"), "M start\n?? d/\n?? new.md"; got != want {
			t.Errorf("status %q, want %q", got, want)
		}
		if got := m.must(t, a, "status", "--porcelain", "--untracked-files=no"); got != "M start" {
			t.Errorf("status of the tracked %q", got)
		}
		if got, want := m.must(t, a, "ls-files", "-z", "--cached", "--others", "--exclude-standard"), "d/e.md\x00new.md\x00.gitignore\x00start\x00"; got != want {
			t.Errorf("ls-files %q, want %q", got, want)
		}
		for path, want := range map[string]int{"bin/": 0, "x.log": 0, "new.md": 1} {
			if _, code := m.git(t, a, "check-ignore", "-q", "--no-index", filepath.FromSlash(path)); code != want {
				t.Errorf("check-ignore %s: exit %d, want %d", path, code, want)
			}
		}
		m.must(t, a, "add", ".")
		if _, code := m.git(t, a, "commit", "-q", "-m", "all"); code != 0 {
			t.Fatal("commit all")
		}
		if got := m.must(t, a, "status", "--porcelain"); got != "" {
			t.Errorf("after the commit, status %q", got)
		}
		if _, code := m.git(t, a, "commit", "-q", "-m", "nothing"); code != 1 {
			t.Errorf("a commit of nothing: exit %d", code)
		}
	})
	t.Run("a detached worktree takes a merge it does not commit, and is removed", func(t *testing.T) {
		t.Parallel()
		m := fresh(t)
		_, a, b := m.boxes(t)
		m.commit(t, b, "y", "b\n")
		m.must(t, b, "push", "-q", "origin", "main:issue-1")
		m.commit(t, a, "x", "a\n")
		m.must(t, a, "fetch", "-q", "origin", "issue-1")
		theirs := m.must(t, a, "rev-parse", "FETCH_HEAD")
		tree := filepath.Join(a, "rules", "issue-1")
		m.must(t, a, "worktree", "add", "-q", "--detach", tree, "main")
		head := m.must(t, tree, "rev-parse", "HEAD")
		m.must(t, tree, "merge", "-q", "--no-commit", "--no-ff", theirs)
		for _, f := range []string{"x", "y"} {
			if there, _ := m.disk.Exists(filepath.Join(tree, f)); !there {
				t.Errorf("the merge lacks %s", f)
			}
		}
		if got := m.must(t, tree, "rev-parse", "HEAD"); got != head {
			t.Fatalf("the merge was committed: %s", got)
		}
		if got := m.must(t, tree, "ls-files", "--unmerged"); got != "" {
			t.Fatalf("a clean merge lists %q unmerged", got)
		}
		if _, code := m.git(t, a, "worktree", "remove", tree); code != 128 {
			t.Fatalf("a worktree mid-merge removed without --force: exit %d", code)
		}
		m.must(t, a, "worktree", "remove", "--force", tree)
		if there, _ := m.disk.Exists(tree); there {
			t.Fatal("the worktree stands after its removal")
		}
		if _, code := m.git(t, a, "worktree", "remove", "--force", tree); code != 128 {
			t.Fatalf("a worktree removed twice: exit %d", code)
		}
		if _, code := m.git(t, a, "worktree", "remove", "--force", a); code != 128 {
			t.Fatalf("the main work tree removed: exit %d", code)
		}
		// Both sides change one file apart: the merge stops, and lists it.
		m.commit(t, a, "y", "a\n")
		m.must(t, a, "worktree", "add", "-q", "--detach", tree, "HEAD")
		if _, code := m.git(t, tree, "merge", "-q", "--no-commit", "--no-ff", theirs); code == 0 {
			t.Fatal("a conflict merged")
		}
		if got := m.must(t, tree, "ls-files", "--unmerged"); !strings.HasSuffix(got, "\ty") {
			t.Fatalf("the conflict lists %q unmerged", got)
		}
		m.must(t, a, "worktree", "remove", "--force", tree)
		if dirty := m.must(t, a, "status", "--porcelain"); dirty != "" {
			t.Fatalf("the clone changed: %q", dirty)
		}
	})
	t.Run("a pull fast-forwards, and branches and worktrees check out what they hold", func(t *testing.T) {
		t.Parallel()
		m := fresh(t)
		_, a, b := m.boxes(t)
		m.commit(t, a, "x", "a\n")
		m.must(t, a, "push", "-q", "origin", "main")
		m.must(t, b, "pull", "-q", "--ff-only", "origin", "main")
		if got, want := m.must(t, b, "rev-parse", "HEAD"), m.must(t, a, "rev-parse", "HEAD"); got != want {
			t.Fatalf("b is at %s after the pull, want %s", got, want)
		}
		m.must(t, b, "checkout", "-q", "-b", "w", "main~1")
		if there, _ := m.disk.Exists(filepath.Join(b, "x")); there {
			t.Fatal("x stands on a branch from before it")
		}
		m.must(t, b, "checkout", "-q", "main")
		if there, _ := m.disk.Exists(filepath.Join(b, "x")); !there {
			t.Fatal("x is gone back on main")
		}
		if _, code := m.git(t, b, "checkout", "-q", "-b", "w"); code != 128 {
			t.Fatalf("a branch made twice: exit %d", code)
		}
		m.must(t, a, "push", "-q", "origin", "main:issue-3")
		m.must(t, b, "fetch", "-q", "origin", "issue-3:refs/remotes/origin/issue-3")
		tree := filepath.Join(m.root, "issue-3")
		m.must(t, b, "worktree", "add", "--track", "-b", "issue-3", tree, "origin/issue-3")
		if got := m.must(t, tree, "rev-parse", "--abbrev-ref", "@{upstream}"); got != "origin/issue-3" {
			t.Fatalf("the worktree tracks %s", got)
		}
		if data, err := m.disk.ReadFile(filepath.Join(tree, "x")); err != nil || string(data) != "a\n" {
			t.Fatalf("the worktree holds %q, %v", data, err)
		}
		if got := m.must(t, b, "branch", "--list", "issue-3"); !strings.HasSuffix(got, "issue-3") {
			t.Fatalf("b's branches: %q", got)
		}
		m.commit(t, a, "z", "a\n")
		m.must(t, a, "push", "-q", "origin", "main")
		m.commit(t, b, "y", "b\n")
		if _, code := m.git(t, b, "pull", "-q", "--ff-only", "origin", "main"); code == 0 {
			t.Fatal("a pull that cannot fast-forward went through")
		}
		if err := m.disk.RemoveAll(filepath.Join(m.root, "origin.git")); err != nil {
			t.Fatal(err)
		}
		if _, code := m.git(t, a, "pull", "-q", "--ff-only", "origin", "main"); code == 0 {
			t.Fatal("a pull from an origin that is gone went through")
		}
	})
	t.Run("a worktree inside the checkout merges without committing, and goes", func(t *testing.T) {
		t.Parallel()
		m := fresh(t)
		_, a, b := m.boxes(t)
		m.commit(t, a, "x", "a\n")
		m.must(t, a, "push", "-q", "origin", "main")
		m.must(t, b, "checkout", "-q", "-b", "side")
		m.commit(t, b, "y", "b\n")
		m.must(t, b, "push", "-q", "origin", "side")
		m.must(t, b, "checkout", "-q", "-b", "clash", "main")
		m.commit(t, b, "x", "b\n")
		m.must(t, b, "push", "-q", "origin", "clash")
		m.must(t, a, "fetch", "-q", "origin", "main")
		main := m.must(t, a, "rev-parse", "FETCH_HEAD")
		for branch, conflicts := range map[string]bool{"side": false, "clash": true} {
			m.must(t, a, "fetch", "-q", "origin", branch)
			head := m.must(t, a, "rev-parse", "FETCH_HEAD")
			wt := filepath.Join(a, ".se", ".runtime", "rules", branch)
			m.must(t, a, "worktree", "add", "-q", "--detach", wt, main)
			_, code := m.git(t, wt, "merge", "-q", "--no-commit", "--no-ff", head)
			if unmerged := m.must(t, wt, "ls-files", "--unmerged"); (code != 0) != conflicts || (unmerged != "") != conflicts {
				t.Errorf("%s: merge exit %d, unmerged %q", branch, code, unmerged)
			}
			if there, _ := m.disk.Exists(filepath.Join(wt, "y")); there == conflicts {
				t.Errorf("%s: the merge holds y: %v", branch, there)
			}
			if _, code := m.git(t, a, "worktree", "remove", wt); code == 0 {
				t.Errorf("%s: a worktree mid-merge went without --force", branch)
			}
			m.must(t, a, "worktree", "remove", "--force", wt)
			if there, _ := m.disk.Exists(wt); there {
				t.Errorf("%s: the worktree's folder stands", branch)
			}
		}
		if got := m.must(t, a, "status", "--porcelain"); got != "" {
			t.Fatalf("the checkout changed: %q", got)
		}
	})
}
