// Package cli is the core's command line, the same for the bare core and for
// every application built on it: an application's main registers its
// components (index.Register) and calls Run with its own name.
//
//	<name> start  [--root DIR] [--grace D] [--idle D]   start the core in the background, return at once
//	<name> status [--root DIR] [--wait D] [--json]      say whether a core runs, and its health
//	<name> stop   [--root DIR]                          stop the core and wait until it has exited
//	<name> serve  [--root DIR] [--grace D] [--idle D]   run the core in the foreground (what start spawns)
//	<name> hook <event> [--root DIR] [--wait D] [--unanswered N]  post the host's hook JSON on stdin to the core
//
// The root is the checkout the core serves: by default the nearest folder up
// from the working directory that holds .git, else the working directory.
// Exit codes: 0 done, 1 no core runs (status), 2 a usage or start error.
// hook exits 0 and prints nothing where the core does not answer: a hook
// fails open, and a host reads a hook's exit code 2 as a block. With
// --unanswered N it exits N instead where no command answered the event (no
// core, none bound to it, or the bound one failed), so its caller can answer
// it another way.
package cli

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"time"

	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// HoldEnv names a file a served core waits for before it stands its bus: a
// test's way to show that `kern start` returns before the core answers.
const HoldEnv = "KERN_HOLD_START"

// StepWaitEnv names a duration that replaces the served core's StepWait, the
// silence it waits out from one step of a declared command: a test's way to
// show that a step that beats outlives it.
const StepWaitEnv = "KERN_STEP_WAIT"

const usage = "usage: %s <start|status|stop|serve|hook <event>> [--root DIR] [--grace D] [--idle D] [--wait D] [--json] [--unanswered N]"

// Run is the command named name: it serves the components registered with
// index.Register before it is called, and answers the exit code.
func Run(name string, args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		fmt.Fprintf(stderr, usage+"\n", name)
		return 2
	}
	verb := args[0]
	if verb == "hook" {
		return hook(name, args[1:], os.Stdin, stdout, stderr)
	}
	fs := flag.NewFlagSet(name+" "+verb, flag.ContinueOnError)
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
		fmt.Fprintf(stderr, "%s: no command %q\n"+usage+"\n", name, verb, name)
		return 2
	}
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	dir, err := rootOf(*root)
	if err != nil {
		fmt.Fprintf(stderr, "%s %s: %v\n", name, verb, err)
		return 2
	}
	switch verb {
	case "start":
		bin, err := os.Executable()
		if err != nil {
			fmt.Fprintf(stderr, "%s start: no path to this binary: %v\n", name, err)
			return 2
		}
		got, err := host.Start(host.Wall{}, dir, bin, "--grace", grace.String(), "--idle", idle.String())
		if err != nil {
			fmt.Fprintln(stderr, err)
			return 2
		}
		fmt.Fprintf(stdout, "%s: %s in %s\n", name, got, dir)
		return 0
	case "status":
		st, err := host.WaitRunning(host.Wall{}, dir, *wait)
		if err != nil {
			fmt.Fprintf(stderr, "%s status: %v\n", name, err)
			return 2
		}
		if *asJSON {
			data, _ := json.Marshal(map[string]any{"state": st.State, "health": st.Health})
			fmt.Fprintln(stdout, string(data))
		} else if st.State == host.StateRunning {
			h := st.Health
			fmt.Fprintf(stdout, "%s: running in %s, pid %d, bus %s, %d session(s), %d instance(s), %d placed\n",
				name, dir, h.Pid, h.Bus, len(h.Sessions), len(h.Instances), len(h.Placements))
		} else {
			fmt.Fprintf(stdout, "%s: %s in %s\n", name, st.State, dir)
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
			fmt.Fprintf(stdout, "%s: not running in %s\n", name, dir)
		} else {
			fmt.Fprintf(stdout, "%s: stopped pid %d in %s\n", name, pid, dir)
		}
		return 0
	}
	return serve(name, dir, *grace, *idle, stdout, stderr)
}

// hook posts the host's hook JSON, read from stdin, on hook.<event> and
// prints the answer as the host's hook JSON: the output of the command bound
// to the event, else the context the components told, on an event that
// carries context (HookOutput). A pass with nothing told prints nothing; so
// does every failure, which goes to stderr alone, with the exit code
// --unanswered names, 0 by default.
func hook(name string, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet(name+" hook", flag.ContinueOnError)
	fs.SetOutput(stderr)
	root := fs.String("root", "", "the checkout the core serves")
	wait := fs.Duration("wait", host.HookWait, "how long to wait for the core's answer, a start included")
	unanswered := fs.Int("unanswered", 0, "the exit code where no command answered the event")
	event := ""
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		event, args = args[0], args[1:]
	}
	if err := fs.Parse(args); err != nil {
		return 0
	}
	if event == "" && fs.NArg() > 0 {
		event = fs.Arg(0)
	}
	dir, err := rootOf(*root)
	if err != nil {
		fmt.Fprintf(stderr, "%s hook: %v\n", name, err)
		return 0
	}
	payload, err := io.ReadAll(stdin)
	if err != nil {
		fmt.Fprintf(stderr, "%s hook: stdin: %v\n", name, err)
		return 0
	}
	a, err := host.Post(host.Wall{}, dir, event, payload, *wait)
	switch {
	case err != nil:
		fmt.Fprintf(stderr, "%s hook: %v\n", name, err)
	case a.Effect == host.Output:
		if a.Output != "" {
			fmt.Fprintln(stdout, strings.TrimRight(a.Output, "\n"))
		}
		return 0
	case a.Error != "":
		fmt.Fprintf(stderr, "%s hook: %s\n", name, a.Error)
	default:
		if out := HookOutput(event, a); out != nil {
			stdout.Write(append(out, '\n'))
			return 0
		}
	}
	return *unanswered
}

// ContextEvents are the host's events whose hook output hands the agent
// context: Claude Code reads hookSpecificOutput.additionalContext on these.
var ContextEvents = map[string]bool{"PostToolUse": true, "UserPromptSubmit": true, "SessionStart": true}

// HookOutput is the host's hook JSON for the core's answer to event: the
// context the components told, on an event that carries it; nil for none.
func HookOutput(event string, a host.HookAnswer) []byte {
	if a.Context == "" || !ContextEvents[event] {
		return nil
	}
	out, _ := json.Marshal(map[string]any{"hookSpecificOutput": map[string]string{
		"hookEventName": event, "additionalContext": a.Context}})
	return out
}

// serve runs the core until it ends: no session holds a lease, it is idle,
// it is asked to stop, or the process is interrupted.
func serve(name, root string, grace, idle time.Duration, stdout, stderr io.Writer) int {
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
			fmt.Fprintf(stderr, "%s serve: %v\n", name, err)
			return 2
		}
	}
	var stepWait time.Duration
	if v := os.Getenv(StepWaitEnv); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil || d <= 0 {
			fmt.Fprintf(stderr, "%s serve: %s=%q is no duration, such as 60s\n", name, StepWaitEnv, v)
			return 2
		}
		stepWait = d
	}
	// The ad hoc wiring overlay, .se/wiring.toml, holds the instances `se
	// component add` placed under the ignored .se/ (index.ReadWiring comment on
	// Merge); it is read after the tracked wiring and merged into it.
	overlay := filepath.Join(root, ".se", index.WiringFile)
	if _, err := os.Stat(overlay); err == nil {
		o, err := index.ReadWiring(overlay)
		if err != nil {
			fmt.Fprintf(stderr, "%s serve: %v\n", name, err)
			return 2
		}
		w.Merge(o)
	}
	core, err := host.Serve(host.Options{
		Root: root, Wiring: w, Components: index.Registered(), Grace: grace, Idle: idle, Log: stderr,
		StepWait: stepWait,
	})
	if err != nil {
		fmt.Fprintln(stderr, err)
		_ = os.Remove(host.ClaimPath(root))
		return 2
	}
	fmt.Fprintf(stdout, "%s: serving %s, pid %d, bus %s\n", name, root, os.Getpid(), core.Health().Bus)
	interrupt := make(chan os.Signal, 1)
	signal.Notify(interrupt, os.Interrupt)
	select {
	case <-core.Ended():
	case <-interrupt:
		core.Stop("interrupted")
		<-core.Ended()
	}
	fmt.Fprintf(stdout, "%s: ended, %s\n", name, core.Reason())
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
