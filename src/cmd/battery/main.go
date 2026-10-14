// Command battery profiles tests/check.sh (src/internal/battery). check.sh
// runs `battery gotest <top> <packages>` for its Go tests, which runs go test
// -json and keeps every test's duration, `battery plugintest <top> <plugin>`
// for its plugin tests, which runs `claude plugin test` and keeps what it
// printed, each test's duration among it, and `battery report <top>` once every
// step has passed, which prints the profile against spec/budgets.yaml, writes
// it for the CI summary and se issue land, and fails only on a hard budget's
// overrun. top is the checkout, where the battery's files live.
package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// machine is the disk the battery reads and writes.
var machine = disk.Real()

func main() {
	// check.sh runs the battery in src/, where go.mod is, and names the
	// checkout's top, where its files live.
	if len(os.Args) < 3 {
		fail(fmt.Errorf("usage: battery gotest <top> <packages> | battery plugintest <top> <plugin> | battery report <top>"))
	}
	top := os.Args[2]
	switch os.Args[1] {
	case "gotest":
		fail(gotest(proc.Real(), top, os.Args[3:]))
	case "plugintest":
		fail(plugintest(proc.Real(), top, os.Args[3:]))
	case "report":
		fail(report(top))
	default:
		fail(fmt.Errorf("battery has no command %q", os.Args[1]))
	}
}

// gotest runs go test -json on the packages, shows what go test shows a
// person, keeps the events for report, and fails as go test failed. It runs
// go test with GIT_DIR on a decoy repository, and fails if a test changed it.
// It keeps the events under the checkout top, and runs git and go on procs.
func gotest(procs proc.Procs, top string, packages []string) error {
	dir, err := machine.MkdirTemp("", "battery-decoy-")
	if err != nil {
		return err
	}
	defer func() { _ = machine.RemoveAll(dir) }()
	decoy, err := battery.NewDecoy(machine, procs, dir)
	if err != nil {
		return err
	}
	raw, err := machine.Create(filepath.Join(top, battery.Dir, battery.GoTestFile))
	if err != nil {
		return err
	}
	defer raw.Close()
	events, written := io.Pipe()
	run, err := procs.Start(proc.Cmd{
		Name: "go", Args: append([]string{"test", "-json"}, packages...),
		Env: decoy.Env(os.Environ()), Stdout: written, Stderr: os.Stderr,
	})
	if err != nil {
		return err
	}
	relaying := make(chan error, 1)
	go func() {
		err := battery.Relay(events, os.Stdout, raw)
		// What Relay left unread must not hold go test up.
		_, _ = io.Copy(io.Discard, events)
		relaying <- err
	}()
	waited := run.Wait()
	_ = written.Close()
	relayed := <-relaying
	if err := decoy.Check(); err != nil {
		return err
	}
	if waited != nil {
		return fmt.Errorf("go test: %v", waited)
	}
	return relayed
}

// plugintest runs `claude plugin test` on the plugin, shows what it prints,
// keeps a copy under the checkout top for report, and fails as it failed.
// `claude plugin test` has no reporter option, so report reads each plugin
// test's duration from the lines it prints for a person.
func plugintest(procs proc.Procs, top string, plugin []string) error {
	raw, err := machine.Create(filepath.Join(top, battery.Dir, battery.PluginTestFile))
	if err != nil {
		return err
	}
	defer raw.Close()
	kept := battery.Lock(raw)
	if err := procs.Run(proc.Cmd{
		Name: "claude", Args: append([]string{"plugin", "test"}, plugin...),
		Stdout: io.MultiWriter(os.Stdout, kept), Stderr: io.MultiWriter(os.Stderr, kept),
	}); err != nil {
		return fmt.Errorf("claude plugin test: %v", err)
	}
	return nil
}

// report prints the profile of the battery just run in the checkout at top,
// and adds it to the CI job's summary where there is one.
func report(top string) error {
	var summary io.Writer
	if path := os.Getenv("GITHUB_STEP_SUMMARY"); path != "" {
		f, err := machine.Append(path)
		if err != nil {
			return err
		}
		defer f.Close()
		summary = f
	}
	p, err := battery.Report(machine, top, summary)
	fmt.Print(p.Text())
	return err
}

func fail(err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "battery: %v\n", err)
		os.Exit(1)
	}
}
