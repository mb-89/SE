package proc_test

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/mb-89/SE/src/modules/io/proc"
)

// asTool is the first word that makes this test binary run as tool.
const asTool = "se-proc-contract-tool"

// TestMain runs the test binary as tool when the contract starts it so: the
// real machine's tool is this very binary, on every system the tests run on.
func TestMain(m *testing.M) {
	if len(os.Args) > 1 && os.Args[1] == asTool {
		dir, _ := os.Getwd()
		os.Exit(tool(os.Args[2:], dir, os.Getenv, os.Stdin, os.Stdout, os.Stderr))
	}
	os.Exit(m.Run())
}

func TestTheRealMachineKeepsTheContract(t *testing.T) {
	t.Parallel()
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	contract(t, func(*testing.T) toolOn {
		return toolOn{procs: proc.Real(), run: func(words ...string) proc.Cmd {
			return proc.Cmd{Name: self, Args: append([]string{asTool}, words...), Env: os.Environ()}
		}}
	})
}

func TestAProgramStillOpenForWritingIsBusy(t *testing.T) {
	t.Parallel()
	if runtime.GOOS != "linux" {
		t.Skip("text file busy is Linux's")
	}
	path := filepath.Join(t.TempDir(), "script")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY, 0o755)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if _, err := f.WriteString("#!/bin/sh\nexit 0\n"); err != nil {
		t.Fatal(err)
	}
	err = proc.Real().Run(proc.Cmd{Name: path})
	if !errors.Is(err, proc.ErrBusy) {
		t.Fatalf("got %v, want ErrBusy", err)
	}
	if _, ok := proc.ExitCode(err); ok {
		t.Fatal("a busy program has an exit code")
	}
}
