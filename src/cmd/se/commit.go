package main

import (
	"os"
	"path/filepath"
	"runtime/debug"
	"strings"

	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/update"
)

// commit is the SE commit this se was built from. Every build sets it:
// go build -ldflags "-X main.commit=$(git rev-parse HEAD)" -o src/plugin/bin/se ./src/cmd/se
var commit string

// What the plugin tells se on every session call: the commit its hooks were
// loaded from, and the checkout it was loaded from.
const (
	hooksCommitEnv = "SE_HOOKS_COMMIT"
	pluginRepoEnv  = "SE_PLUGIN_CHECKOUT"
)

// builtFrom is the commit this se was built from, or "" where nobody knows.
// A build without the ldflags falls back to the revision Go recorded.
func builtFrom() string {
	if commit != "" {
		return commit
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
func pluginCheckout() string {
	if repo := os.Getenv(pluginRepoEnv); repo != "" {
		return repo
	}
	exe, err := executable()
	if err != nil {
		return ""
	}
	return filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(exe))))
}

// commits says where the session's SE came from: the commit its hooks were
// loaded from, the commit the plugin's checkout is at now, the commit the
// running se was built from, and whether they agree. "" is a commit nobody knows.
func commits(hooks, checkout, built string) string {
	known := func(c string) string {
		if c == "" {
			return "unknown"
		}
		return short(c)
	}
	lines := []string{
		"Hooks loaded from:   " + known(hooks),
		"Plugin checkout at:  " + known(checkout),
		"se built from:       " + known(built),
	}
	var unknown []string
	for _, c := range []struct{ name, commit string }{{"the hooks'", hooks}, {"the checkout's", checkout}, {"se's", built}} {
		if c.commit == "" {
			unknown = append(unknown, c.name)
		}
	}
	switch {
	case len(unknown) > 0:
		lines = append(lines, "Whether they agree is unknown: "+strings.Join(unknown, ", ")+" commit is not known.")
	case hooks == checkout && built == checkout:
		lines = append(lines, "They agree.")
	default:
		var off []string
		if hooks != checkout {
			off = append(off, "the hooks are not the checkout's: they load again on /reload-plugins or in a new session")
		}
		if built != checkout {
			off = append(off, "se was not built from the checkout")
		}
		lines = append(lines, "They disagree: "+strings.Join(off, "; ")+".")
	}
	return strings.Join(lines, "\n")
}

// sessionCommits is commits for this call, from what the plugin said and what git says now.
func sessionCommits(procs proc.Procs) string {
	checkout := ""
	if repo := pluginCheckout(); repo != "" {
		checkout, _ = update.Head(procs, repo)
	}
	return commits(os.Getenv(hooksCommitEnv), checkout, builtFrom())
}

// short is a commit as git log --oneline shows it.
func short(c string) string {
	if len(c) > 7 {
		return c[:7]
	}
	return c
}
