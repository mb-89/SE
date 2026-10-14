package proc_test

import (
	"errors"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// onFake is a fake machine with tool installed as "tool", and running as it.
func onFake(*testing.T) toolOn {
	f := proc.NewFake()
	f.Install("tool", func(c proc.Cmd) int {
		getenv := func(name string) string {
			for _, kv := range c.Env {
				if k, v, _ := strings.Cut(kv, "="); k == name {
					return v
				}
			}
			return ""
		}
		return tool(c.Args, c.Dir, getenv, c.Stdin, c.Stdout, c.Stderr)
	})
	f.RunAs("tool")
	return toolOn{procs: f, run: func(words ...string) proc.Cmd { return proc.Cmd{Name: "tool", Args: words} }}
}

func TestTheFakeMachineKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, onFake)
}

func TestAFakeMachineRunningNothingAsItselfHasNoSelf(t *testing.T) {
	t.Parallel()
	if self, err := proc.NewFake().Self(); !errors.Is(err, proc.ErrNotFound) {
		t.Fatalf("self %q, %v", self, err)
	}
}

func TestTheFakeMachineRecordsEveryRunInOrder(t *testing.T) {
	t.Parallel()
	f := proc.NewFake()
	f.Install("git", func(c proc.Cmd) int { return 0 })
	_ = f.Run(proc.Cmd{Name: "git", Args: []string{"status"}, Dir: "/w"})
	if err := f.Run(proc.Cmd{Name: "go", Args: []string{"build"}}); !errors.Is(err, proc.ErrNotFound) {
		t.Fatalf("an uninstalled go ran: %v", err)
	}
	if got, want := f.Lines(), []string{"git status", "go build"}; !slices.Equal(got, want) {
		t.Fatalf("ran %q, want %q", got, want)
	}
	if f.Ran()[0].Dir != "/w" {
		t.Fatalf("the run lost its folder: %+v", f.Ran()[0])
	}
}

func TestTheFakeGitKeepsTheContract(t *testing.T) {
	t.Parallel()
	gitContract(t, func(t *testing.T) gitOn {
		d, m := disk.NewFake(), proc.NewFake()
		m.InstallGit(d)
		root := filepath.FromSlash("/work")
		if err := d.MkdirAll(root); err != nil {
			t.Fatal(err)
		}
		return gitOn{procs: m, disk: d, root: root}
	})
}

func TestAListedMachineStartsOnlyTheListedPrograms(t *testing.T) {
	t.Parallel()
	f := proc.NewFake()
	for _, name := range []string{"git", "gh", "/w/.se/.runtime/bin/se"} {
		f.Install(name, func(proc.Cmd) int { return 0 })
	}
	m := proc.Listed(f)
	if err := m.Run(proc.Cmd{Name: "git", Args: []string{"status"}}); err != nil {
		t.Fatal(err)
	}
	if err := m.Run(proc.Cmd{Name: "/w/.se/.runtime/bin/se", Args: []string{"serve"}}); err != nil {
		t.Fatal(err)
	}
	if err := m.Run(proc.Cmd{Name: "gh", Args: []string{"api", "user"}}); !errors.Is(err, proc.ErrNotListed) {
		t.Fatalf("gh ran: %v", err)
	}
	if _, err := m.Start(proc.Cmd{Name: "gh"}); !errors.Is(err, proc.ErrNotListed) {
		t.Fatalf("gh started: %v", err)
	}
	if got, want := f.Lines(), []string{"git status", "/w/.se/.runtime/bin/se serve"}; !slices.Equal(got, want) {
		t.Fatalf("ran %q, want %q: a refused program never reaches the machine", got, want)
	}
}

func TestEachStartOnAFakeMachinePassesItsDelay(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)
	c := clock.NewFake(at)
	f := proc.NewFake()
	f.Install("git", func(proc.Cmd) int { return 0 })
	f.Delay(c, 50*time.Millisecond)
	for range 3 {
		if err := f.Run(proc.Cmd{Name: "git"}); err != nil {
			t.Fatal(err)
		}
	}
	if took := c.Now().Sub(at); took != 150*time.Millisecond {
		t.Fatalf("three starts took %v, want 150ms", took)
	}
}
