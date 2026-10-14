package proc_test

import (
	"errors"
	"slices"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/proc"
)

// onFake is a fake machine with tool installed as "tool".
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
	return toolOn{procs: f, run: func(words ...string) proc.Cmd { return proc.Cmd{Name: "tool", Args: words} }}
}

func TestTheFakeMachineKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, onFake)
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
