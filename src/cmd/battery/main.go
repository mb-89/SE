// Command battery profiles tests/check.sh (src/internal/battery). check.sh
// runs `battery gotest <packages>` for its Go tests, which runs go test -json
// and keeps every test's duration, and `battery report` once every step has
// passed, which prints the profile against spec/budgets.yaml, writes it for
// the CI summary and se issue land, and fails only on a hard budget's overrun.
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/mb-89/SE/src/internal/battery"
)

func main() {
	if len(os.Args) < 2 {
		fail(fmt.Errorf("usage: battery gotest <packages> | battery report"))
	}
	switch os.Args[1] {
	case "gotest":
		fail(gotest(os.Args[2:]))
	case "report":
		fail(report())
	default:
		fail(fmt.Errorf("battery has no command %q", os.Args[1]))
	}
}

// gotest runs go test -json on the packages, shows what go test shows a
// person, keeps the events for report, and fails as go test failed. It runs
// go test with GIT_DIR on a decoy repository, and fails if a test changed it.
func gotest(packages []string) error {
	dir, err := os.MkdirTemp("", "battery-decoy-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(dir)
	decoy, err := battery.NewDecoy(dir)
	if err != nil {
		return err
	}
	raw, err := os.Create(filepath.Join(battery.Dir, battery.GoTestFile))
	if err != nil {
		return err
	}
	defer raw.Close()
	cmd := exec.Command("go", append([]string{"test", "-json"}, packages...)...)
	cmd.Env = decoy.Env(os.Environ())
	cmd.Stderr = os.Stderr
	events, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	relayed := battery.Relay(events, os.Stdout, raw)
	waited := cmd.Wait()
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
	var summary *os.File
	if path := os.Getenv("GITHUB_STEP_SUMMARY"); path != "" {
		f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		defer f.Close()
		summary = f
	}
	var p battery.Profile
	var err error
	if summary != nil {
		p, err = battery.Report(".", summary)
	} else {
		p, err = battery.Report(".", nil)
	}
	fmt.Print(p.Text())
	return err
}

func fail(err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "battery: %v\n", err)
		os.Exit(1)
	}
}
