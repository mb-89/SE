// se is SE's deterministic side: the workspace daemon the plugin forwards to,
// and the verbs that start, stop and update it.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/mb-89/SE/internal/daemon"
	"github.com/mb-89/SE/internal/update"
)

const usage = `se <verb> [flags]

  serve   run this workspace's daemon in the foreground (the debugger's way in)
  start   answer the running daemon, or start one in the background
  stop    end this workspace's daemon
  status  say whether a daemon answers here
  update  pull main into the installed SE checkout and rebuild se`

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, usage)
		os.Exit(2)
	}
	if err := run(os.Args[1], os.Args[2:]); err != nil {
		fmt.Fprintln(os.Stderr, "se:", err)
		os.Exit(1)
	}
}

func run(verb string, args []string) error {
	fs := flag.NewFlagSet(verb, flag.ContinueOnError)
	workspace := fs.String("workspace", ".", "the workspace the daemon serves")
	idle := fs.Duration("idle", 30*time.Minute, "serve: end after this long without an event; 0 never")
	repo := fs.String("repo", "", "update: the installed SE checkout (default: the one this binary was built into)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	root, err := filepath.Abs(*workspace)
	if err != nil {
		return err
	}
	paths := daemon.Paths{Workspace: root}
	switch verb {
	case "serve":
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		err := daemon.Serve(ctx, paths, daemon.Options{Idle: *idle, Ready: func(ep daemon.Endpoint) {
			fmt.Fprintf(os.Stderr, "se: serving %s at %s\n", root, ep.Address)
		}})
		if errors.Is(err, daemon.ErrRunning) {
			return fmt.Errorf("%w; run se stop --workspace %s first", err, root)
		}
		return err
	case "start":
		exe, err := os.Executable()
		if err != nil {
			return err
		}
		ep, err := daemon.Start(paths, exe, 10*time.Second)
		if err != nil {
			return err
		}
		return printed(ep)
	case "stop":
		return daemon.Stop(paths, 5*time.Second)
	case "status":
		ep, ok := daemon.Healthy(paths)
		if !ok {
			return printed(map[string]any{"running": false})
		}
		return printed(map[string]any{"running": true, "address": ep.Address, "pid": ep.PID, "startedAt": ep.StartedAt})
	case "update":
		exe, err := os.Executable()
		if err != nil {
			return err
		}
		checkout := *repo
		if checkout == "" {
			// se is built to <checkout>/plugin/bin/se.
			checkout = filepath.Dir(filepath.Dir(filepath.Dir(exe)))
		}
		r, err := update.Run(checkout, exe)
		if err != nil {
			return err
		}
		return printed(r)
	default:
		return fmt.Errorf("no verb %q\n%s", verb, usage)
	}
}

func printed(v any) error {
	return json.NewEncoder(os.Stdout).Encode(v)
}
