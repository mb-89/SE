// Command kern is the bare core: the index, its bus and its host, with no
// component of an application compiled in.
//
//	kern start  [--root DIR] [--grace D] [--idle D]   start the core in the background, return at once
//	kern status [--root DIR] [--wait D] [--json]      say whether a core runs, and its health
//	kern stop   [--root DIR]                          stop the core and wait until it has exited
//	kern serve  [--root DIR] [--grace D] [--idle D]   run the core in the foreground (what start spawns)
//
// The root is the checkout the core serves: by default the nearest folder up
// from the working directory that holds .git, else the working directory.
// Exit codes: 0 done, 1 no core runs (status), 2 a usage or start error.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"time"

	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// HoldEnv names a file a served core waits for before it stands its bus: a
// test's way to show that `kern start` returns before the core answers.
const HoldEnv = "KERN_HOLD_START"

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

const usage = "usage: kern <start|status|stop|serve> [--root DIR] [--grace D] [--idle D] [--wait D] [--json]"

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprintln(stderr, usage)
		return 2
	}
	verb := args[0]
	fs := flag.NewFlagSet("kern "+verb, flag.ContinueOnError)
	fs.SetOutput(stderr)
	root := fs.String("root", "", "the checkout the core serves")
	var grace, idle, wait *time.Duration
	var asJSON *bool
	switch verb {
	case "start", "serve":
		grace = fs.Duration("grace", host.Grace, "how long the core runs on once no session holds a lease")
		idle = fs.Duration("idle", host.Idle, "how long the core runs without any event")
	case "status":
		wait = fs.Duration("wait", 0, "how long to wait for a starting core to answer")
		asJSON = fs.Bool("json", false, "print the health as JSON")
	case "stop":
	default:
		fmt.Fprintf(stderr, "kern: no command %q\n%s\n", verb, usage)
		return 2
	}
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	dir, err := rootOf(*root)
	if err != nil {
		fmt.Fprintf(stderr, "kern %s: %v\n", verb, err)
		return 2
	}
	switch verb {
	case "start":
		bin, err := os.Executable()
		if err != nil {
			fmt.Fprintf(stderr, "kern start: no path to this binary: %v\n", err)
			return 2
		}
		got, err := host.Start(host.Wall{}, dir, bin, "--grace", grace.String(), "--idle", idle.String())
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 2
		}
		fmt.Fprintf(stdout, "kern: %s in %s\n", got, dir)
		return 0
	case "status":
		st, err := host.WaitRunning(host.Wall{}, dir, *wait)
		if err != nil {
			fmt.Fprintf(stderr, "kern status: %v\n", err)
			return 2
		}
		if *asJSON {
			data, _ := json.Marshal(map[string]any{"state": st.State, "health": st.Health})
			fmt.Fprintln(stdout, string(data))
		} else if st.State == host.StateRunning {
			h := st.Health
			fmt.Fprintf(stdout, "kern: running in %s, pid %d, bus %s, %d session(s), %d instance(s), %d placed\n",
				dir, h.Pid, h.Bus, len(h.Sessions), len(h.Instances), len(h.Placements))
		} else {
			fmt.Fprintf(stdout, "kern: %s in %s\n", st.State, dir)
		}
		if st.State == host.StateStopped {
			return 1
		}
		return 0
	case "stop":
		pid, err := host.AskStop(dir)
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 2
		}
		if pid == 0 {
			fmt.Fprintf(stdout, "kern: not running in %s\n", dir)
		} else {
			fmt.Fprintf(stdout, "kern: stopped pid %d in %s\n", pid, dir)
		}
		return 0
	}
	return serve(dir, *grace, *idle, stdout, stderr)
}

// serve runs the core until it ends: no session holds a lease, it is idle,
// it is asked to stop, or the process is interrupted.
func serve(root string, grace, idle time.Duration, stdout, stderr io.Writer) int {
	if hold := os.Getenv(HoldEnv); hold != "" {
		for {
			if _, err := os.Stat(hold); err == nil {
				break
			}
			time.Sleep(time.Millisecond)
		}
	}
	var w index.Wiring
	path := filepath.Join(root, index.WiringFile)
	if _, err := os.Stat(path); err == nil {
		if w, err = index.ReadWiring(path); err != nil {
			fmt.Fprintf(stderr, "kern serve: %v\n", err)
			return 2
		}
	}
	core, err := host.Serve(host.Options{
		Root: root, Wiring: w, Components: index.Registered(), Grace: grace, Idle: idle, Log: stderr,
	})
	if err != nil {
		fmt.Fprintln(stderr, err)
		_ = os.Remove(host.ClaimPath(root))
		return 2
	}
	fmt.Fprintf(stdout, "kern: serving %s, pid %d, bus %s\n", root, os.Getpid(), core.Health().Bus)
	interrupt := make(chan os.Signal, 1)
	signal.Notify(interrupt, os.Interrupt)
	select {
	case <-core.Ended():
	case <-interrupt:
		core.Stop("interrupted")
		<-core.Ended()
	}
	fmt.Fprintf(stdout, "kern: ended, %s\n", core.Reason())
	return 0
}

// rootOf answers the checkout: the folder given, else the nearest one up from
// the working directory that holds .git, else the working directory.
func rootOf(given string) (string, error) {
	if given != "" {
		abs, err := filepath.Abs(given)
		if err != nil {
			return "", err
		}
		if st, err := os.Stat(abs); err != nil || !st.IsDir() {
			return "", fmt.Errorf("--root %s is no folder", given)
		}
		return abs, nil
	}
	wd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for dir := wd; ; {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return dir, nil
		} else if !errors.Is(err, os.ErrNotExist) {
			return "", err
		}
		up := filepath.Dir(dir)
		if up == dir {
			return wd, nil
		}
		dir = up
	}
}
