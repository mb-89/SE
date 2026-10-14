// Internal test package: package main cannot be imported.
package main

import (
	"fmt"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/update"
)

// sePlugin is a fake git's SE checkout, whose origin/main stands at main and
// holds the commits contains says are in it.
type sePlugin struct {
	dir, main string
	contains  map[string]bool
	fetched   bool
}

func (p *sePlugin) git(c proc.Cmd) int {
	switch args := c.Args; {
	case c.Dir != p.dir:
		return 128
	case strings.Join(args, " ") == "fetch -q origin main":
		p.fetched = true
	case strings.Join(args, " ") == "rev-parse origin/main":
		fmt.Fprintln(c.Stdout, p.main)
	case len(args) == 4 && args[0] == "merge-base" && args[1] == "--is-ancestor" && args[2] == p.main:
		if known, ok := p.contains[args[3]]; !ok {
			return 128
		} else if !known {
			return 1
		}
	default:
		return 1
	}
	return 0
}

// onPlugin puts the se of the test into an SE checkout at dir, built from
// built, whose origin/main stands at main and is in the commits contains says.
func onPlugin(t *testing.T, built, main string, contains map[string]bool) *sePlugin {
	t.Helper()
	p := &sePlugin{dir: t.TempDir(), main: main, contains: contains}
	put(t, worldOf(t).Disk, filepath.Join(p.dir, update.ModuleDir, "go.mod"), "module "+update.Module+"\n")
	m := proc.NewFake()
	m.Install("git", p.git)
	m.RunAs(filepath.Join(p.dir, "src", "plugin", "bin", "se"))
	onMachine(t, m)
	worldOf(t).Commit = built
	return p
}

func TestATakeBySeBuiltBeforeMainMovedIsRefusedNamingTheUpdate(t *testing.T) {
	t.Parallel()
	p := onPlugin(t, aaa, bbb, map[string]bool{aaa: false})
	code, _, errs := se(t, "issue", "pull", "--take", "--repo", "o/r")
	if code != 1 || !p.fetched || !strings.Contains(errs, "se was built from aaaaaaa, but main has moved on to bbbbbbb") || !strings.Contains(errs, "Run se update") {
		t.Fatalf("exit %d, %q", code, errs)
	}
	if code, _, errs := se(t, "issue", "pull", "--in", "3", "--take", "--repo", "o/r"); code != 1 || !strings.Contains(errs, "Run se update") {
		t.Fatalf("--in: exit %d, %q", code, errs)
	}
}

func TestStaleSeLetsATakeGoWhereMainIsInTheBuildOrNobodyKnows(t *testing.T) {
	t.Parallel()
	for _, c := range []struct {
		name, built, main string
		contains          map[string]bool
	}{
		{"built from main", aaa, aaa, nil},
		{"built from a branch on main", aaa, bbb, map[string]bool{aaa: true}},
		{"a build this checkout lacks", aaa, bbb, nil},
		{"the build unknown", "", bbb, nil},
	} {
		t.Run(c.name, func(t *testing.T) {
			t.Parallel()
			onPlugin(t, c.built, c.main, c.contains)
			if err := staleSE(worldOf(t)); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestStaleSeLetsATakeGoOutsideAnSECheckout(t *testing.T) {
	t.Parallel()
	m := proc.NewFake()
	m.Install("git", func(proc.Cmd) int { t.Error("git ran outside an SE checkout"); return 1 })
	m.RunAs(filepath.Join(t.TempDir(), "src", "plugin", "bin", "se"))
	onMachine(t, m)
	worldOf(t).Commit = aaa
	if err := staleSE(worldOf(t)); err != nil {
		t.Fatal(err)
	}
}
