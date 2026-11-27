package start_test

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"kern/git"
	"kern/git/gitfake"
	"se/components/start"
)

// Every test reaches git through kern's git door, on its fake.
func TestMain(m *testing.M) {
	git.Use(gitfake.New())
	os.Exit(m.Run())
}

var ctx = context.Background()

func write(t *testing.T, path, text string) string {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}

// fresh is a fresh clone of a project with an se.toml, as a cloud session's container clones it:
// no core.hooksPath, which git never copies, and git's own hooks folder in its .git (the fake
// keeps no .git on disk, so the test makes the folder git's real clone has). Its home is a folder
// of its own, so the machine's ~/.se/local.toml is not read.
func fresh(t *testing.T) (clone, base string) {
	t.Helper()
	base = t.TempDir()
	t.Setenv("HOME", filepath.Join(base, "home"))
	t.Setenv("USERPROFILE", filepath.Join(base, "home"))
	clone = filepath.Join(base, "clone")
	write(t, filepath.Join(clone, "se.toml"), "[project]\nversion = \"0.1.0\"\n")
	if err := os.MkdirAll(filepath.Join(clone, ".git", "hooks"), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := git.Run(ctx, clone, "init", "-q"); err != nil {
		t.Fatal(err)
	}
	if got := hooksPath(t, clone); got != "" {
		t.Fatalf("a fresh clone has core.hooksPath %q", got)
	}
	return clone, base
}

func hooksPath(t *testing.T, repo string) string {
	t.Helper()
	out, err := git.Run(ctx, repo, "config", "--get", "core.hooksPath")
	if err != nil {
		return ""
	}
	return strings.TrimSpace(out)
}

func TestSetHooksPointsAFreshCloneOfSEAtItsOwnHooksOnce(t *testing.T) {
	clone, base := fresh(t)
	write(t, filepath.Join(clone, ".githooks", "se-script"), "#!/bin/sh\n") // se's own checkout carries its hooks
	for range 2 {                                                           // again: no change
		if line := start.SetHooks(ctx, filepath.Join(base, "plugin"), clone); line != "" {
			t.Fatalf("line %q", line)
		}
		if got := hooksPath(t, clone); got != ".githooks" { // as setup.sh sets it in se's own checkout
			t.Fatalf("core.hooksPath %q", got)
		}
	}
}

func TestSetHooksLeavesASetHooksPathAlone(t *testing.T) {
	clone, base := fresh(t)
	if _, err := git.Run(ctx, clone, "config", "core.hooksPath", "custom/hooks"); err != nil {
		t.Fatal(err)
	}
	if line := start.SetHooks(ctx, filepath.Join(base, "plugin"), clone); line != "" {
		t.Fatalf("line %q", line)
	}
	if got := hooksPath(t, clone); got != "custom/hooks" {
		t.Fatalf("core.hooksPath %q", got)
	}
}

func TestSetHooksNamesTheCheckoutsOwnHooksThatStopRunningAndTheCommandThatKeepsThem(t *testing.T) {
	clone, base := fresh(t)
	folder := filepath.Join(clone, ".git", "hooks")
	write(t, filepath.Join(folder, "pre-commit"), "#!/bin/sh\n") // a hook set such as the pre-commit framework's
	write(t, filepath.Join(folder, "pre-push.sample"), "#!/bin/sh\n")
	line := start.SetHooks(ctx, filepath.Join(base, "plugin"), clone)
	if got, want := hooksPath(t, clone), filepath.ToSlash(filepath.Join(base, "plugin", ".githooks")); got != want {
		t.Fatalf("core.hooksPath %q, want %q", got, want)
	}
	f, c := filepath.ToSlash(folder), filepath.ToSlash(clone)
	want := "SE: the hooks in " + f + " no longer run: pre-commit, as core.hooksPath now names se's; to keep them, run: git -C " +
		c + " config core.hooksPath " + f + " (se's public check then does not run on this checkout's commits)"
	if line != want {
		t.Fatalf("line\n%q, want\n%q", line, want)
	}
	if line := start.SetHooks(ctx, filepath.Join(base, "plugin"), clone); line != "" { // a set one stays
		t.Fatalf("again: line %q", line)
	}
}

func TestSetHooksSaysNothingOfAHooksFolderWithOnlySamples(t *testing.T) {
	clone, base := fresh(t)
	write(t, filepath.Join(clone, ".git", "hooks", "pre-commit.sample"), "#!/bin/sh\n")
	if line := start.SetHooks(ctx, filepath.Join(base, "plugin"), clone); line != "" {
		t.Fatalf("line %q", line)
	}
	if got, want := hooksPath(t, clone), filepath.ToSlash(filepath.Join(base, "plugin", ".githooks")); got != want {
		t.Fatalf("core.hooksPath %q, want %q", got, want)
	}
}

func TestTheHooksThatStopRunningAreEveryNameButASampleSorted(t *testing.T) {
	if got := start.Stopped([]string{"pre-push", "commit-msg.sample", "pre-commit", "post-merge"}); !reflect.DeepEqual(got, []string{"post-merge", "pre-commit", "pre-push"}) {
		t.Fatal(got)
	}
	if got := start.Stopped([]string{"pre-commit.sample"}); len(got) != 0 {
		t.Fatal(got)
	}
	if got := start.Stopped(nil); len(got) != 0 {
		t.Fatal(got)
	}
}

func TestOwnNamesTheHooksForSetupAndNoneWhereTheFolderIsSEsOwn(t *testing.T) {
	clone, _ := fresh(t)
	folder := filepath.Join(clone, ".git", "hooks")
	write(t, filepath.Join(folder, "pre-commit"), "#!/bin/sh\n")
	if got, stopped := start.Own(ctx, clone, ".githooks"); got != folder || !reflect.DeepEqual(stopped, []string{"pre-commit"}) {
		t.Fatalf("Own: %q %v", got, stopped)
	}
	if _, stopped := start.Own(ctx, clone, folder); len(stopped) != 0 {
		t.Fatalf("the folder itself stops %v", stopped)
	}
}

// A linked worktree's own hooks are those of its repository's common folder, which its .git file
// names through commondir, as git's `rev-parse --git-path hooks` answers.
func TestOwnReadsALinkedWorktreesHooksFromItsCommonFolder(t *testing.T) {
	clone, base := fresh(t)
	main := filepath.Join(base, "main")
	write(t, filepath.Join(main, ".git", "hooks", "pre-push"), "#!/bin/sh\n")
	write(t, filepath.Join(main, ".git", "worktrees", "clone", "commondir"), "../..\n")
	if err := os.RemoveAll(filepath.Join(clone, ".git")); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(clone, ".git"), "gitdir: "+filepath.Join(main, ".git", "worktrees", "clone")+"\n")
	folder, stopped := start.Own(ctx, clone, ".githooks")
	if folder != filepath.Join(main, ".git", "hooks") || !reflect.DeepEqual(stopped, []string{"pre-push"}) {
		t.Fatalf("Own: %q %v", folder, stopped)
	}
}

func TestSetHooksTakesTheHooksOfTheSEComponentAProjectPinsElseThisSEs(t *testing.T) {
	clone, base := fresh(t)
	plugin := filepath.Join(base, "plugin")
	if line := start.SetHooks(ctx, plugin, clone); line != "" {
		t.Fatalf("line %q", line)
	}
	if got, want := hooksPath(t, clone), filepath.ToSlash(filepath.Join(plugin, ".githooks")); got != want { // no se component: this SE's hooks
		t.Fatalf("core.hooksPath %q, want %q", got, want)
	}
	pinning := filepath.Join(base, "pinning")
	write(t, filepath.Join(pinning, "se.toml"), "[components.se]\nref = \""+strings.Repeat("0", 40)+"\"\n")
	if _, err := git.Run(ctx, pinning, "init", "-q"); err != nil {
		t.Fatal(err)
	}
	module := filepath.Join(base, "se-module")
	write(t, filepath.Join(module, ".githooks", "se-script"), "#!/bin/sh\n")
	write(t, filepath.Join(base, "home", ".se", "local.toml"), "[paths]\nse = \""+filepath.ToSlash(module)+"\"\n")
	if line := start.SetHooks(ctx, plugin, pinning); line != "" {
		t.Fatalf("line %q", line)
	}
	if got, want := hooksPath(t, pinning), filepath.ToSlash(filepath.Join(module, ".githooks")); got != want { // the pinned se's, as its setup.sh sets
		t.Fatalf("core.hooksPath %q, want %q", got, want)
	}
}

func TestSetHooksChangesNothingOutsideAProjectCheckout(t *testing.T) {
	base := t.TempDir()
	plain := filepath.Join(base, "plain")
	write(t, filepath.Join(plain, "se.toml"), "[project]\nversion = \"0.1.0\"\n") // an se.toml, but no git
	if line := start.SetHooks(ctx, filepath.Join(base, "plugin"), plain); line != "" {
		t.Fatalf("line %q", line)
	}
	if line := start.SetHooks(ctx, filepath.Join(base, "plugin"), ""); line != "" {
		t.Fatalf("line %q", line)
	}
}

func TestProjectIsTheNearestFolderWithAnSEToml(t *testing.T) {
	base := t.TempDir()
	write(t, filepath.Join(base, "se.toml"), "")
	deep := filepath.Join(base, "a", "b")
	if err := os.MkdirAll(deep, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CLAUDE_PROJECT_DIR", deep)
	if got := start.Project(""); got != base {
		t.Fatalf("Project %q, want %q", got, base)
	}
	if got := start.Project(deep); got != deep {
		t.Fatalf("Project(given) %q", got)
	}
}
