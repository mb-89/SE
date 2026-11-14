package cli_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/mb-89/kern/cli"
)

// Source serves a checkout its own wiring, wiring.toml or the ad hoc overlay
// alone; a checkout with none is served the home's, where the home has one.
func TestACheckoutWithoutWiringIsServedTheHomes(t *testing.T) {
	write := func(path string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("\n"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	home, bare := t.TempDir(), t.TempDir()
	write(filepath.Join(home, "wiring.toml"))
	own, adHoc, empty := t.TempDir(), t.TempDir(), t.TempDir()
	write(filepath.Join(own, "wiring.toml"))
	write(filepath.Join(adHoc, ".se", "wiring.toml"))
	for _, c := range []struct{ name, root, home, want string }{
		{"its own wiring.toml", own, home, own},
		{"its ad hoc overlay", adHoc, home, adHoc},
		{"none, the home's", empty, home, home},
		{"none, a home without wiring", empty, bare, empty},
		{"none, no home", empty, "", empty},
	} {
		if got := cli.Source(c.root, c.home); got != c.want {
			t.Errorf("%s: Source answers %s, and wants %s", c.name, got, c.want)
		}
	}
}
