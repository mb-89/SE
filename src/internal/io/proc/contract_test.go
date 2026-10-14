package proc_test

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/proc"
)

// tool is the program every contract case runs, on the fake as on the real
// machine. Its words, each done in turn: "out TEXT" writes TEXT to stdout,
// "err TEXT" to stderr, "pwd" writes the folder it runs in, "env NAME" the
// variable's value, "cat" copies stdin to stdout, "exit N" ends with N.
func tool(args []string, dir string, getenv func(string) string, stdin io.Reader, stdout, stderr io.Writer) int {
	for i := 0; i < len(args); i++ {
		next := func() string {
			i++
			if i < len(args) {
				return args[i]
			}
			return ""
		}
		switch args[i] {
		case "out":
			fmt.Fprintln(stdout, next())
		case "err":
			fmt.Fprintln(stderr, next())
		case "pwd":
			fmt.Fprintln(stdout, dir)
		case "env":
			fmt.Fprintln(stdout, getenv(next()))
		case "cat":
			_, _ = io.Copy(stdout, bufio.NewReader(stdin))
		case "exit":
			code, _ := strconv.Atoi(next())
			return code
		}
	}
	return 0
}

// toolOn is a machine with tool on it, and how to run tool there.
type toolOn struct {
	procs proc.Procs
	// run is the Cmd that runs tool with these words.
	run func(words ...string) proc.Cmd
}

// contract is the one suite every Procs keeps, the fake as the real one.
// fresh answers a new machine with tool on it for each case.
func contract(t *testing.T, fresh func(t *testing.T) toolOn) {
	t.Run("run answers what the program wrote, each stream apart", func(t *testing.T) {
		m := fresh(t)
		var out, errs bytes.Buffer
		c := m.run("out", "hello", "err", "trouble")
		c.Stdout, c.Stderr = &out, &errs
		if err := m.procs.Run(c); err != nil {
			t.Fatal(err)
		}
		if out.String() != "hello\n" || errs.String() != "trouble\n" {
			t.Fatalf("stdout %q, stderr %q", out.String(), errs.String())
		}
	})
	t.Run("an exit other than 0 is an ExitError with its code", func(t *testing.T) {
		m := fresh(t)
		err := m.procs.Run(m.run("exit", "3"))
		var exit *proc.ExitError
		if !errors.As(err, &exit) || exit.Code != 3 {
			t.Fatalf("got %v, want exit status 3", err)
		}
		if code, ok := proc.ExitCode(err); !ok || code != 3 {
			t.Fatalf("ExitCode said %d %v", code, ok)
		}
	})
	t.Run("a program that is not there is not found", func(t *testing.T) {
		m := fresh(t)
		for _, name := range []string{"se-proc-contract-no-such-program", filepath.Join(t.TempDir(), "none")} {
			c := m.run()
			c.Name = name
			if err := m.procs.Run(c); !errors.Is(err, proc.ErrNotFound) {
				t.Fatalf("%s: got %v, want ErrNotFound", name, err)
			}
			if _, err := m.procs.Start(c); !errors.Is(err, proc.ErrNotFound) {
				t.Fatalf("start %s: got %v, want ErrNotFound", name, err)
			}
			if _, ok := proc.ExitCode(m.procs.Run(c)); ok {
				t.Fatal("a program that never ran has an exit code")
			}
		}
	})
	t.Run("the program runs in its folder and reads its environment and stdin", func(t *testing.T) {
		m := fresh(t)
		dir := t.TempDir()
		c := m.run("pwd", "env", "SE_PROC_CONTRACT", "cat")
		c.Dir = dir
		c.Env = append(c.Env, "SE_PROC_CONTRACT=seen")
		c.Stdin = strings.NewReader("fed\n")
		out, err := proc.Output(m.procs, c)
		if err != nil {
			t.Fatal(err)
		}
		lines := strings.Split(out, "\n")
		if len(lines) != 3 || !sameDir(lines[0], dir) || lines[1] != "seen" || lines[2] != "fed" {
			t.Fatalf("got %q, want the folder %s, seen and fed", out, dir)
		}
	})
	t.Run("output names a failure with what the program said", func(t *testing.T) {
		m := fresh(t)
		_, err := proc.Output(m.procs, m.run("out", "kept", "err", "the reason", "exit", "1"))
		if err == nil || !strings.Contains(err.Error(), "the reason") || !strings.Contains(err.Error(), "exit status 1") {
			t.Fatalf("got %v", err)
		}
		said, err := proc.Combined(m.procs, m.run("out", "one", "err", "two", "exit", "2"))
		if code, _ := proc.ExitCode(err); code != 2 || !strings.Contains(string(said), "one") || !strings.Contains(string(said), "two") {
			t.Fatalf("combined %q, %v", said, err)
		}
	})
	t.Run("start returns before the program ends, and wait answers its end", func(t *testing.T) {
		m := fresh(t)
		in, feed := io.Pipe()
		var out bytes.Buffer
		c := m.run("cat", "exit", "4")
		c.Stdin, c.Stdout, c.Detached = in, &out, true
		r, err := m.procs.Start(c)
		if err != nil {
			t.Fatal(err)
		}
		// The program reads until stdin closes: Start came back while it runs.
		fmt.Fprintln(feed, "late")
		_ = feed.Close()
		if code, _ := proc.ExitCode(r.Wait()); code != 4 || out.String() != "late\n" {
			t.Fatalf("exit %d, wrote %q", code, out.String())
		}
	})
}

// sameDir says whether two paths name one folder, links resolved.
func sameDir(a, b string) bool {
	ra, errA := filepath.EvalSymlinks(a)
	rb, errB := filepath.EvalSymlinks(b)
	return errA == nil && errB == nil && ra == rb
}
