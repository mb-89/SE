// Internal test package: package main cannot be imported.
package main

import (
	"os/exec"
	"strings"
	"testing"
)

// checkout is a git checkout on branch whose origin is gone, so a pull fails.
func checkout(t *testing.T, branch string) string {
	t.Helper()
	dir := t.TempDir()
	for _, args := range [][]string{
		{"init", "-q", "-b", branch},
		{"-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "start"},
		{"remote", "add", "origin", dir + "/gone"},
	} {
		if out, err := exec.Command("git", append([]string{"-C", dir}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	return dir
}

func TestAtSessionStartACheckoutOffMainIsLeftAloneInOneLine(t *testing.T) {
	r := session(t, "update", "--session-start", "--repo", checkout(t, "feature"))
	if !strings.HasPrefix(r.Text, "SE left its checkout as it is") || strings.Contains(r.Text, "\n") || r.Reload {
		t.Fatalf("%+v", r)
	}
}

func TestAtSessionStartAFailedPullDoesNotFail(t *testing.T) {
	code, out, _ := se(t, "--session", "--workspace", t.TempDir(), "update", "--session-start", "--repo", checkout(t, "main"))
	if code != 0 || !strings.Contains(out, "the session goes on with the SE it has") || strings.Contains(out, `"reload"`) {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestOutsideSessionStartAFailedPullFails(t *testing.T) {
	code, out, _ := se(t, "--session", "--workspace", t.TempDir(), "update", "--repo", checkout(t, "main"))
	if code != 1 || !strings.Contains(out, "se update: git pull") {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestAnUpdateOverARemoteConnectionDoesNotReload(t *testing.T) {
	t.Setenv(remoteEnv, "true")
	if reloads(true) {
		t.Fatal("a remote session was asked to reload")
	}
	t.Setenv(remoteEnv, "")
	if !reloads(true) || reloads(false) {
		t.Fatal("only a local session reloads")
	}
}
