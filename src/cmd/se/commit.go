package main

import (
	"path/filepath"
	"runtime/debug"
	"strings"

	"github.com/mb-89/SE/src/internal/update"
)

// commit is the SE commit this se was built from, which src/build.sh and
// update.Build set; the plugin's bootstrap build leaves it to the revision Go
// recorded.
var commit string

// What the plugin tells se on every session call: the commit its hooks were
// loaded from, and the checkout it was loaded from.
const (
	hooksCommitEnv = "SE_HOOKS_COMMIT"
	pluginRepoEnv  = "SE_PLUGIN_CHECKOUT"
)

// builtFrom is the commit this se was built from, or "" where nobody knows.
// A build without the ldflags falls back to the revision Go recorded.
func builtFrom(w *World) string {
	if w.Commit != "" {
		return w.Commit
	}
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, s := range info.Settings {
			if s.Key == "vcs.revision" {
				return s.Value
			}
		}
	}
	return ""
}

// pluginCheckout is the checkout the session's plugin was loaded from: the one
// the plugin names, else the one this se was built into (<checkout>/src/plugin/bin/se).
func pluginCheckout(w *World) string {
	if repo := w.Getenv(pluginRepoEnv); repo != "" {
		return repo
	}
	exe, err := w.Proc.Self()
	if err != nil {
		return ""
	}
	return filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(exe))))
}

// commits says where the session's SE came from, kept to its point: one line
// where the commit its hooks were loaded from, the commit the plugin's
// checkout is at now and the commit the running se was built from agree;
// else one short line per commit, and the remedy once. "" is a commit nobody
// knows.
func commits(hooks, checkout, built string) string {
	if hooks != "" && hooks == checkout && built == checkout {
		return "Hooks, checkout and se agree at " + short(checkout) + "."
	}
	known := func(c string) string {
		if c == "" {
			return "unknown"
		}
		return short(c)
	}
	lines := []string{
		"Hooks loaded from " + known(hooks) + ".",
		"Checkout at " + known(checkout) + ".",
		"se built from " + known(built) + ".",
	}
	if hooks == "" || checkout == "" || built == "" {
		return strings.Join(append(lines, "Whether they agree is unknown."), "\n")
	}
	return strings.Join(append(lines, "They disagree: start a new session."), "\n")
}

// sessionCommits is commits for this call, from what the plugin said and what git says now.
func sessionCommits(w *World) string {
	checkout := ""
	if repo := pluginCheckout(w); repo != "" {
		checkout, _ = update.Head(w.Proc, repo)
	}
	return commits(w.Getenv(hooksCommitEnv), checkout, builtFrom(w))
}

// short is a commit as git log --oneline shows it.
func short(c string) string {
	if len(c) > 7 {
		return c[:7]
	}
	return c
}
