// Internal test package: package main cannot be imported.
package main

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/proc"
)

// checkout answers a box's checkout on branch, on the machine every call of
// the test is handed, with an origin that is gone, so a pull fails.
func checkout(t *testing.T, branch string) string {
	t.Helper()
	ws := clone(t)
	if branch != "main" {
		git(t, ws, "checkout", "-q", "-b", branch)
	}
	if err := onFake(t).RemoveAll(filepath.Join(filepath.Dir(ws), "origin.git")); err != nil {
		t.Fatal(err)
	}
	// The se running is the one built into the checkout.
	worldOf(t).Proc.(*proc.Fake).RunAs(filepath.Join(ws, "src", "plugin", "bin", "se"))
	return ws
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
