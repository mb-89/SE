// Internal test package: package main cannot be imported.
package main

import (
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// commandBudgets are spec/budgets.yaml's budgets for the interactive commands.
func commandBudgets(t *testing.T) battery.CommandBudgets {
	t.Helper()
	// This reads the checkout's own budgets, so it reads the real disk.
	b, err := battery.ReadBudgets(disk.Real(), "../../..")
	if err != nil {
		t.Fatal(err)
	}
	c := b.Commands
	if c.Interactive.Ms <= 0 || c.Interactive.Requests <= 0 || c.Latency.RequestMs <= 0 || c.Latency.ProcessMs <= 0 {
		t.Fatalf("%s budgets the interactive commands at %+v", battery.BudgetsFile, c)
	}
	return c
}

// measured runs se name on a fake o/r whose every GitHub request and process
// start takes the budgets' latency on the call's clock, and answers its
// outside requests and how long it took by that clock.
func measured(t *testing.T, name string, b battery.CommandBudgets) battery.Command {
	t.Helper()
	gh := recordedIssues(t)
	w := worldOf(t)
	clk := w.Clock.(*clock.Fake)
	gh.Delay(clk, time.Duration(b.Latency.RequestMs)*time.Millisecond)
	machine := proc.NewFake()
	for _, p := range proc.Programs {
		machine.Install(p, func(proc.Cmd) int { return 0 })
	}
	machine.Delay(clk, time.Duration(b.Latency.ProcessMs)*time.Millisecond)
	w.Proc = machine
	args := append([]string{"--workspace", t.TempDir()}, strings.Fields(name)...)
	if slices.Contains(commandFlags()[name], "repo") {
		args = append(args, "--repo", "o/r")
	}
	start := clk.Now()
	code, out, errs := se(t, args...)
	if code != 0 {
		t.Fatalf("se %s: exit %d, %q %q", name, code, out, errs)
	}
	return battery.Command{Name: name, Requests: gh.Requests() + len(machine.Ran()), Ms: clk.Now().Sub(start).Milliseconds()}
}

// TestEveryInteractiveCommandKeepsItsBudget holds principle 9: a person never
// waits on the outside world. Each interactive command runs within its time
// and request budget, or is named in the budgets' over list, which only
// shrinks. Each run goes to the battery's profile.
func TestEveryInteractiveCommandKeepsItsBudget(t *testing.T) {
	t.Parallel()
	b := commandBudgets(t)
	var interactive []string
	for _, c := range catalog().Commands {
		if c.Class == index.Interactive {
			interactive = append(interactive, c.Name)
		}
	}
	for _, name := range b.Over {
		if !slices.Contains(interactive, name) {
			t.Errorf("%s names %q over its budget, but it is no interactive command; remove it", battery.BudgetsFile, name)
		}
	}
	for _, name := range interactive {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			run := measured(t, name, b)
			t.Log(battery.CommandLine(run))
			over := run.Ms > b.Interactive.Ms || run.Requests > b.Interactive.Requests
			switch {
			case over && !slices.Contains(b.Over, name):
				t.Errorf("se %s took %dms and %d outside requests, over its budget of %dms and %d requests (%s): answer from the snapshot (principle 9)",
					name, run.Ms, run.Requests, b.Interactive.Ms, b.Interactive.Requests, battery.BudgetsFile)
			case !over && slices.Contains(b.Over, name):
				t.Errorf("se %s keeps its budget now (%dms, %d requests); remove it from the over list in %s, which only shrinks",
					name, run.Ms, run.Requests, battery.BudgetsFile)
			}
		})
	}
}

func TestEveryCommandDeclaresItsClass(t *testing.T) {
	t.Parallel()
	for _, c := range catalog().Commands {
		if c.Class != index.Interactive && c.Class != index.Batch {
			t.Errorf("se %s declares the class %q", c.Name, c.Class)
		}
	}
}
