// Package start is SE's session start in Go (docs/start.md "Start and refresh"), the port of
// scripts/se_start.py, step by step: the `se` binary's verbs call it (cmd/se/start.go). It holds
// the start's hooks step: the project's core.hooksPath set to se's hooks where it is unset, and
// the checkout's own hooks that stop running once it names them. Its git goes through kern's git
// door.
package start

import (
	"context"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"kern/git"
	"se/components/template"
)

// Hooks is the folder of se's git hooks, beside the se-script they run (AGENTS.md "Public safety").
const Hooks = ".githooks"

// Stopped is the hooks a checkout's own hooks folder holds that stop running once core.hooksPath
// names another folder: each file name there that is no `.sample`, sorted.
func Stopped(names []string) []string {
	found := []string{}
	for _, name := range names {
		if !strings.HasSuffix(name, ".sample") {
			found = append(found, name)
		}
	}
	sort.Strings(found)
	return found
}

// StoppedLine is the one line that says a checkout's own hooks no longer run, and the command
// that keeps them.
func StoppedLine(checkout, folder string, names []string) string {
	return "SE: the hooks in " + folder + " no longer run: " + strings.Join(names, ", ") +
		", as core.hooksPath now names se's; to keep them, run: git -C " + checkout +
		" config core.hooksPath " + folder + " (se's public check then does not run on this checkout's commits)"
}

// Own is the hooks folder git runs for the checkout at root now (its core.hooksPath, else git's
// own hooks folder) and the hooks in it that stop running once core.hooksPath names hooks; no
// folder, one with only `.sample` files, or hooks itself, stops none. An empty hooks names none.
func Own(ctx context.Context, root, hooks string) (string, []string) {
	folder := ""
	if out, err := git.Run(ctx, root, "config", "--get", "core.hooksPath"); err == nil {
		folder = strings.TrimSpace(out)
	}
	if folder == "" {
		folder = gitHooks(ctx, root)
	}
	if folder == "" {
		return root, nil
	}
	if !filepath.IsAbs(folder) {
		folder = filepath.Join(root, folder)
	}
	entries, err := os.ReadDir(folder)
	if err != nil {
		return folder, nil
	}
	if hooks != "" {
		named := hooks
		if !filepath.IsAbs(named) {
			named = filepath.Join(root, named)
		}
		if same(named, folder) {
			return folder, nil
		}
	}
	var names []string
	for _, entry := range entries {
		if entry.Type().IsRegular() {
			names = append(names, entry.Name())
		}
	}
	return folder, Stopped(names)
}

// gitHooks is git's own hooks folder for the checkout at root, where core.hooksPath is unset:
// `hooks` in the repository's common git folder, which a linked worktree's `.git` file names
// through its `commondir`; empty outside a work tree.
func gitHooks(ctx context.Context, root string) string {
	prefix, err := git.Run(ctx, root, "rev-parse", "--show-prefix")
	if err != nil {
		return ""
	}
	top := filepath.Clean(root)
	for _, part := range strings.Split(strings.Trim(strings.TrimSpace(prefix), "/"), "/") {
		if part != "" {
			top = filepath.Dir(top)
		}
	}
	dotgit := filepath.Join(top, ".git")
	info, err := os.Stat(dotgit)
	if err != nil {
		return ""
	}
	if info.IsDir() {
		return filepath.Join(dotgit, "hooks")
	}
	data, err := os.ReadFile(dotgit)
	if err != nil {
		return ""
	}
	gitdir := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(string(data)), "gitdir:"))
	if !filepath.IsAbs(gitdir) {
		gitdir = filepath.Join(top, gitdir)
	}
	common := gitdir
	if text, err := os.ReadFile(filepath.Join(gitdir, "commondir")); err == nil {
		common = strings.TrimSpace(string(text))
		if !filepath.IsAbs(common) {
			common = filepath.Join(gitdir, common)
		}
	}
	return filepath.Join(common, "hooks")
}

// same says whether a and b name one folder, their links resolved where they exist.
func same(a, b string) bool {
	resolve := func(p string) string {
		if r, err := filepath.EvalSymlinks(p); err == nil {
			p = r
		}
		if abs, err := filepath.Abs(p); err == nil {
			p = abs
		}
		return filepath.Clean(p)
	}
	return resolve(a) == resolve(b)
}

func isFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

// SetHooks is the start's hooks step: it points a project checkout whose core.hooksPath is unset
// at se's hooks, as scripts/setup.sh does, so a fresh clone's first commit already runs the public
// check. A checkout that has one keeps it, whatever it names. The hooks are the checkout's own
// where it carries se's (se's own checkout, `.githooks`), else those of the se component its
// se.toml pins, else those of the SE at seRoot. It answers the line to show: empty where nothing
// changed, else the checkout's own hooks that stop running with the command that keeps them; it
// fails open.
func SetHooks(ctx context.Context, seRoot, root string) string {
	if root == "" || !isFile(filepath.Join(root, "se.toml")) {
		return ""
	}
	if out, err := git.Run(ctx, root, "config", "--get", "core.hooksPath"); err == nil && strings.TrimSpace(out) != "" {
		return ""
	}
	if _, err := git.Run(ctx, root, "rev-parse", "--show-prefix"); err != nil {
		return "" // no work tree: nothing commits here
	}
	hooks := filepath.ToSlash(filepath.Join(seRoot, Hooks))
	if isFile(filepath.Join(root, Hooks, "se-script")) {
		hooks = Hooks
	} else if dir, pinned, err := template.ComponentDir(root, "se"); err == nil && pinned &&
		isFile(filepath.Join(dir, Hooks, "se-script")) {
		hooks = filepath.ToSlash(filepath.Join(dir, Hooks)) // else the start goes on with this SE's hooks
	}
	folder, stopped := Own(ctx, root, hooks)
	if _, err := git.Run(ctx, root, "config", "core.hooksPath", hooks); err != nil {
		return "SE: setting core.hooksPath of " + filepath.ToSlash(root) + " failed; run: sh " +
			filepath.ToSlash(filepath.Join(seRoot, "scripts", "setup.sh")) + " " + filepath.ToSlash(root)
	}
	if len(stopped) == 0 {
		return ""
	}
	return StoppedLine(filepath.ToSlash(root), filepath.ToSlash(folder), stopped)
}

// Project is the project the start runs for: given, else the nearest folder from
// $CLAUDE_PROJECT_DIR (else the working folder) up that holds an se.toml, as se_modules.py
// `find_root` finds it; empty where none does.
func Project(given string) string {
	if given != "" {
		if abs, err := filepath.Abs(given); err == nil {
			return abs
		}
		return given
	}
	dir := os.Getenv("CLAUDE_PROJECT_DIR")
	if dir == "" {
		dir, _ = os.Getwd()
	}
	dir, _ = filepath.Abs(dir)
	for {
		if isFile(filepath.Join(dir, "se.toml")) {
			return dir
		}
		up := filepath.Dir(dir)
		if up == dir {
			return ""
		}
		dir = up
	}
}
