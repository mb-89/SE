package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/mb-89/SE/internal/daemon"
)

func init() {
	register(Command{
		Name:    "serve",
		Usage:   "serve [--idle D] [--takeover]",
		Summary: "run this workspace's daemon in the foreground (the debugger's way in); --idle 0 never idles out",
		Run: func(c *Call) (Reply, error) {
			fs := c.Flags("serve")
			idle := fs.Duration("idle", 30*time.Minute, "end after this long without an event; 0 never")
			takeover := fs.Bool("takeover", false, "ask a daemon already running for this workspace to step down, and take its place")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			opts := daemon.Options{Idle: *idle, Ready: func(ep daemon.Endpoint) {
				fmt.Fprintf(os.Stderr, "se: serving %s at %s\n", c.Workspace, ep.Address)
			}}
			if *takeover {
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
