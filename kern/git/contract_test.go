package git_test

// The door's contract: what kern and SE's Go components rely on git to do,
// held once against real git and against the fake every other Go test uses
// (gitfake), as SE's tests/test_git_door.py holds SE's Python door. This file
// is the only Go test that runs real git on purpose; its real run sets its own
// home, global config and identity, so a runner's bare git config cannot
// change what it sees. Values git formats differently across versions (a UTC
// date as Z or +00:00) are compared parsed.

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/git"
	"github.com/mb-89/kern/git/gitfake"
)

var identity = []string{"-c", "user.name=alice", "-c", "user.email=alice@example.com"}

// isolated is real git with nothing of the machine's configuration: like a
// bare CI runner it knows no identity, and it may not guess one.
func isolated(t *testing.T) git.Backend {
	home := t.TempDir()
	config := filepath.Join(home, "gitconfig")
	text := "[user]\n\tuseConfigOnly = true\n[maintenance]\n\tauto = false\n[gc]\n\tauto = 0\n" +
		"[commit]\n\tgpgsign = false\n[core]\n\tautocrlf = false\n"
	if err := os.WriteFile(config, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	return git.Real{Env: []string{"HOME=" + home, "XDG_CONFIG_HOME=" + home, "GIT_CONFIG_NOSYSTEM=1",
		"GIT_CONFIG_GLOBAL=" + config, "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
		"GIT_COMMITTER_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE", "EMAIL", "GIT_DIR", "GIT_WORK_TREE"}}
}

// contract runs a case against the fake and against real git.
func contract(t *testing.T, c func(t *testing.T, d door)) {
	for _, kind := range []string{"fake", "real"} {
		t.Run(kind, func(t *testing.T) {
			b := git.Backend(gitfake.New())
			if kind == "real" {
				b = isolated(t)
			}
			c(t, door{t, b})
		})
	}
}

type door struct {
	t *testing.T
	b git.Backend
}

// run runs git in dir, answering its output and error.
func (d door) run(dir string, env []string, args ...string) (string, error) {
	return d.b.Run(context.Background(), git.Command{Dir: dir, Args: args, Env: env})
}

// must runs git in dir and fails the case where git refuses.
func (d door) must(dir string, args ...string) string {
	d.t.Helper()
	out, err := d.run(dir, nil, args...)
	if err != nil {
		d.t.Fatal(err)
	}
	return out
}

func write(t *testing.T, root, rel, text string) {
	t.Helper()
	p := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
}

// project answers a repository on main with files committed in one commit.
func (d door) project(files map[string]string) string {
	root := d.t.TempDir()
	d.must(root, "init", "-q", "-b", "main")
	for rel, text := range files {
		write(d.t, root, rel, text)
	}
	d.must(root, "add", "-A")
	d.must(root, append(identity, "commit", "-q", "-m", "first")...)
	return root
}

func split(out string) []string {
	var names []string
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if line != "" {
			names = append(names, line)
		}
	}
	return names
}

// A commit without an identity is refused, naming it; one named with -c, or
// set in the repository's config, commits.
func TestACommitWithoutAnIdentityIsRefused(t *testing.T) {
	contract(t, func(t *testing.T, d door) {
		root := t.TempDir()
		d.must(root, "init", "-q", "-b", "main")
		write(t, root, "a.txt", "a\n")
		d.must(root, "add", "-A")
		_, err := d.run(root, nil, "commit", "-q", "-m", "first")
		var refused *git.Error
		if !errors.As(err, &refused) || refused.Code == 0 || !strings.Contains(strings.ToLower(refused.Stderr), "identity") {
			t.Fatalf("a commit without an identity answers %v", err)
		}
		d.must(root, append(identity, "commit", "-q", "-m", "first")...)
		d.must(root, "config", "user.name", "bob")
		d.must(root, "config", "user.email", "bob@example.com")
		write(t, root, "b.txt", "b\n")
		d.must(root, "add", "-A")
		d.must(root, "commit", "-q", "-m", "second")
		if got := strings.TrimSpace(d.must(root, "config", "--get", "user.name")); got != "bob" {
			t.Fatalf("config --get user.name answers %q", got)
		}
	})
}

// Outside a repository a command fails with git's exit code 128.
func TestACommandOutsideARepositoryFails(t *testing.T) {
	contract(t, func(t *testing.T, d door) {
		_, err := d.run(t.TempDir(), nil, "ls-files", "--others", "--exclude-standard")
		var refused *git.Error
		if !errors.As(err, &refused) || refused.Code != 128 {
			t.Fatalf("ls-files outside a repository answers %v", err)
		}
	})
}

// rev-parse names the folder's prefix under the root (none at the root) and
// verifies a tag's commit, failing quietly with exit code 1 for a missing one.
func TestRevParseNamesThePrefixAndVerifiesATag(t *testing.T) {
	contract(t, func(t *testing.T, d door) {
		root := d.project(map[string]string{"app/lib/a.go": "package lib\n"})
		if got := d.must(root, "rev-parse", "--show-prefix"); strings.TrimSpace(got) != "" {
			t.Fatalf("the root's prefix is %q", got)
		}
		if got := d.must(filepath.Join(root, "app", "lib"), "rev-parse", "--show-prefix"); strings.TrimSpace(got) != "app/lib/" {
			t.Fatalf("app/lib's prefix is %q", got)
		}
		d.must(root, "tag", "app-v0.1.0")
		head := strings.TrimSpace(d.must(root, "rev-parse", "HEAD"))
		if got := strings.TrimSpace(d.must(root, "rev-parse", "-q", "--verify", "refs/tags/app-v0.1.0^{commit}")); got != head || len(got) != 40 {
			t.Fatalf("the tag's commit is %q, HEAD %q", got, head)
		}
		out, err := d.run(root, nil, "rev-parse", "-q", "--verify", "refs/tags/app-v0.2.0^{commit}")
		var refused *git.Error
		if !errors.As(err, &refused) || refused.Code != 1 || strings.TrimSpace(out+refused.Stderr) != "" {
			t.Fatalf("a missing tag answers %q, %v", out, err)
		}
	})
}

// diff --name-only against a tag names, from the root and from any folder,
// the tracked files changed or deleted since and those added to the index,
// sorted; files git does not track are not named.
func TestDiffAgainstATagNamesTheTrackedFilesChangedSince(t *testing.T) {
	contract(t, func(t *testing.T, d door) {
		root := d.project(map[string]string{"app/go.mod": "module app\n", "app/lib/a.go": "package lib\n",
			"app/lib/b.go": "package lib\n", "README.md": "# r\n"})
		d.must(root, "tag", "v1")
		write(t, root, "app/lib/a.go", "package lib\n// changed\n")
		if err := os.Remove(filepath.Join(root, "app", "lib", "b.go")); err != nil {
			t.Fatal(err)
		}
		write(t, root, "app/lib/new.go", "package lib\n")
		write(t, root, "app/staged.go", "package app\n")
		d.must(root, "add", "app/staged.go")
		want := []string{"app/lib/a.go", "app/lib/b.go", "app/staged.go"}
		for _, dir := range []string{root, filepath.Join(root, "app")} {
			if got := split(d.must(dir, "diff", "--name-only", "--no-renames", "v1", "--")); !reflect.DeepEqual(got, want) {
				t.Fatalf("diff in %s names %v, want %v", dir, got, want)
			}
		}
	})
}

// ls-files --others --exclude-standard names the files under the folder git
// neither tracks nor the root .gitignore ignores: relative to the folder, or
// from the root with --full-name, narrowed by a path after --.
func TestLsFilesOthersNamesTheUntrackedFilesNotIgnored(t *testing.T) {
	contract(t, func(t *testing.T, d door) {
		root := d.project(map[string]string{".gitignore": "build/\n*.log\n", "scripts/tracked.py": "print(1)\n"})
		write(t, root, "scripts/adhoc.py", "print(2)\n")
		write(t, root, "scripts/run.log", "x\n")
		write(t, root, "build/out.py", "x\n")
		write(t, root, "other/x.py", "x\n")
		cases := []struct {
			dir  string
			args []string
			want []string
		}{
			{root, nil, []string{"other/x.py", "scripts/adhoc.py"}},
			{filepath.Join(root, "scripts"), nil, []string{"adhoc.py"}},
			{filepath.Join(root, "scripts"), []string{"--full-name"}, []string{"scripts/adhoc.py"}},
			{root, []string{"--", "scripts/adhoc.py"}, []string{"scripts/adhoc.py"}},
			{root, []string{"--", "scripts/tracked.py"}, nil},
			{root, []string{"--", "build/out.py"}, nil},
		}
		for _, c := range cases {
			got := split(d.must(c.dir, append([]string{"ls-files", "--others", "--exclude-standard"}, c.args...)...))
			if !reflect.DeepEqual(got, c.want) {
				t.Fatalf("ls-files in %s with %v names %v, want %v", c.dir, c.args, got, c.want)
			}
		}
		// -C names the folder as Dir does.
		got := split(d.must("", "-C", root, "ls-files", "--others", "--exclude-standard", "--", "scripts/adhoc.py"))
		if !reflect.DeepEqual(got, []string{"scripts/adhoc.py"}) {
			t.Fatalf("ls-files with -C names %v", got)
		}
	})
}

// for-each-ref names the refs under a prefix, sorted, with lstrip and the
// committer date the commit was made at; a symbolic ref names its target's.
func TestForEachRefNamesTheRefsWithTheirCommitterDate(t *testing.T) {
	contract(t, func(t *testing.T, d door) {
		root := t.TempDir()
		d.must(root, "init", "-q", "-b", "main")
		dated := func(when string) []string {
			return []string{"GIT_COMMITTER_DATE=" + when, "GIT_AUTHOR_DATE=" + when}
		}
		if _, err := d.run(root, dated("2026-11-13T09:00:00Z"), append(identity, "commit", "-q", "--allow-empty", "-m", "one")...); err != nil {
			t.Fatal(err)
		}
		d.must(root, "update-ref", "refs/remotes/origin/feat/x", "HEAD")
		if _, err := d.run(root, dated("2026-11-13T10:30:00+02:00"), append(identity, "commit", "-q", "--allow-empty", "-m", "two")...); err != nil {
			t.Fatal(err)
		}
		d.must(root, "update-ref", "refs/remotes/origin/main", "HEAD")
		d.must(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
		d.must(root, "update-ref", "refs/remotes/upstream/main", "HEAD")
		out := d.must(root, "for-each-ref", "--format=%(refname:lstrip=3)%09%(committerdate:iso-strict)", "refs/remotes/origin/")
		got := map[string]time.Time{}
		var order []string
		for _, line := range split(out) {
			name, when, _ := strings.Cut(line, "\t")
			at, err := time.Parse(time.RFC3339, when)
			if err != nil {
				t.Fatalf("for-each-ref line %q: %v", line, err)
			}
			got[name] = at
			order = append(order, name)
		}
		if !reflect.DeepEqual(order, []string{"HEAD", "feat/x", "main"}) {
			t.Fatalf("for-each-ref names %v", order)
		}
		one, two := time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC), time.Date(2026, 11, 13, 8, 30, 0, 0, time.UTC)
		if !got["feat/x"].Equal(one) || !got["main"].Equal(two) || !got["HEAD"].Equal(two) {
			t.Fatalf("for-each-ref dates %v", got)
		}
	})
}
