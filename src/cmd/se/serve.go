package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/daemon"
)

func init() {
	register(Command{
		Name:    "serve",
		Class:   batch,
		Usage:   "serve [--idle D] [--takeover]",
		Group:   "Daemon",
		Summary: "run this workspace's daemon in the foreground",
		Details: "run this workspace's daemon in the foreground: the debugger's way in.",
		Flags: []index.Flag{
			{Name: "idle", Default: 30 * time.Minute, Help: "end after this long (`D`) without an event; 0 never"},
			{Name: "takeover", Default: false, Help: "ask a daemon already running for this workspace to step down, and take its place"},
		},
		Run: func(c *Call) (Reply, error) {
			ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			opts := daemon.Options{Idle: c.Args.Duration("idle"), Clock: c.Clock, Net: c.Net, Modules: modules(c.Paths(), c.Clock, c.GitHub), Ready: func(ep daemon.Endpoint) {
				fmt.Fprintf(os.Stderr, "se: serving %s at %s\n", c.Workspace, ep.Address)
			}}
			if c.Args.Bool("takeover") {
				opts.TakeOver = 30 * time.Second
			}
			err := daemon.Serve(ctx, c.Paths(), opts)
			if errors.Is(err, daemon.ErrRunning) {
				return Reply{}, fmt.Errorf("%w; run se stop --workspace %s first, or serve with --takeover", err, c.Workspace)
			}
			return Reply{}, err
		},
	})
}
