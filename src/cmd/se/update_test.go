// Internal test package: package main cannot be imported.
package main

import (
	"fmt"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// gitCheckout is a fake git's one checkout: the branch it is on, at head,
// with an origin that is gone, so a pull fails.
type gitCheckout struct{ dir, branch, head string }

func (w gitCheckout) git(c proc.Cmd) int {
	if c.Dir != w.dir {
		fmt.Fprintf(c.Stderr, "fatal: not a git repository: %s\n", c.Dir)
		return 128
	}
	switch args := strings.Join(c.Args, " "); {
	case args == "rev-parse --is-inside-work-tree":
		fmt.Fprintln(c.Stdout, "true")
	case args == "rev-parse --abbrev-ref HEAD":
		fmt.Fprintln(c.Stdout, w.branch)
	case strings.HasPrefix(args, "status --porcelain"):
	case args == "rev-parse HEAD":
		fmt.Fprintln(c.Stdout, w.head)
	case args == "rev-parse --short HEAD":
		fmt.Fprintln(c.Stdout, short(w.head))
	case strings.HasPrefix(args, "pull "):
		fmt.Fprintln(c.Stderr, "fatal: '/gone' does not appear to be a git repository")
		return 1
	default:
		fmt.Fprintf(c.Stderr, "git: this checkout does not do %s\n", args)
		return 1
	}
	return 0
}

// checkout puts a fake git with one checkout on branch on the machine every
// call is handed, for this test, and answers the checkout's folder.
func checkout(t *testing.T, branch string) string {
	t.Helper()
	w := gitCheckout{dir: t.TempDir(), branch: branch, head: strings.Repeat("c", 40)}
	m := proc.NewFake()
	worldOf(t).Git = git.NewFake(w.git)
	// The se running is the one built into the checkout.
	m.RunAs(filepath.Join(w.dir, "src", "plugin", "bin", "se"))
	onMachine(t, m)
	return w.dir
}

// onMachine hands every call m, for this test.
func onMachine(t *testing.T, m proc.Procs) {
	t.Helper()
	worldOf(t).Proc = m
}

func TestAtSessionStartACheckoutOffMainIsLeftAloneInOneLine(t *testing.T) {
	t.Parallel()
	r := session(t, "update", "--session-start", "--repo", checkout(t, "feature"))
	if !strings.HasPrefix(r.Text, "SE left its checkout as it is") || strings.Contains(r.Text, "\n") || r.Reload {
		t.Fatalf("%+v", r)
	}
}

func TestAtSessionStartAFailedPullDoesNotFail(t *testing.T) {
	t.Parallel()
	code, out, _ := se(t, "--session", "--workspace", t.TempDir(), "update", "--session-start", "--repo", checkout(t, "main"))
	if code != 0 || !strings.Contains(out, "the session goes on with the SE it has") || strings.Contains(out, `"reload"`) {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestOutsideSessionStartAFailedPullFails(t *testing.T) {
	t.Parallel()
	code, out, _ := se(t, "--session", "--workspace", t.TempDir(), "update", "--repo", checkout(t, "main"))
	if code != 1 || !strings.Contains(out, "se update: git pull") {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestAnUpdateOverARemoteConnectionDoesNotReload(t *testing.T) {
	t.Parallel()
	setenv(t, remoteEnv, "true")
	if reloads(&Call{Session: true, World: *worldOf(t)}) {
		t.Fatal("a remote session was asked to reload")
	}
	setenv(t, remoteEnv, "")
	if !reloads(&Call{Session: true, World: *worldOf(t)}) || reloads(&Call{World: *worldOf(t)}) {
		t.Fatal("only a local session reloads")
	}
}
