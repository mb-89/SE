// Command battery profiles tests/check.sh (src/internal/battery). check.sh
// runs `battery gotest <packages>` for its Go tests, which runs go test -json
// and keeps every test's duration, and `battery report` once every step has
// passed, which prints the profile against spec/budgets.yaml, writes it for
// the CI summary and se issue land, and fails only on a hard budget's overrun.
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
	if len(os.Args) < 2 {
		fail(fmt.Errorf("usage: battery gotest <packages> | battery report"))
	}
	switch os.Args[1] {
	case "gotest":
		fail(gotest(proc.Real(), os.Args[2:]))
	case "report":
		fail(report())
	default:
		fail(fmt.Errorf("battery has no command %q", os.Args[1]))
	}
}

// gotest runs go test -json on the packages, shows what go test shows a
// person, keeps the events for report, and fails as go test failed. It runs
// go test with GIT_DIR on a decoy repository, and fails if a test changed it.
// It runs git and go on procs.
func gotest(procs proc.Procs, packages []string) error {
	dir, err := machine.MkdirTemp("", "battery-decoy-")
	if err != nil {
		return err
	}
	defer func() { _ = machine.RemoveAll(dir) }()
	decoy, err := battery.NewDecoy(machine, procs, dir)
	if err != nil {
		return err
	}
	raw, err := machine.Create(filepath.Join(battery.Dir, battery.GoTestFile))
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

// report prints the profile of the battery just run, and adds it to the CI
// job's summary where there is one.
func report() error {
	var summary io.Writer
	if path := os.Getenv("GITHUB_STEP_SUMMARY"); path != "" {
		f, err := machine.Append(path)
		if err != nil {
			return err
		}
		defer f.Close()
		summary = f
	}
	p, err := battery.Report(machine, ".", summary)
	fmt.Print(p.Text())
	return err
}

func fail(err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "battery: %v\n", err)
		os.Exit(1)
	}
}
