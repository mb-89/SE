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
		Usage:   "serve [--idle D]",
		Summary: "run this workspace's daemon in the foreground (the debugger's way in); --idle 0 never idles out",
		Run: func(c *Call) (Reply, error) {
			fs := c.Flags("serve")
			idle := fs.Duration("idle", 30*time.Minute, "end after this long without an event; 0 never")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
			defer stop()
			err := daemon.Serve(ctx, c.Paths(), daemon.Options{Idle: *idle, Ready: func(ep daemon.Endpoint) {
				fmt.Fprintf(os.Stderr, "se: serving %s at %s\n", c.Workspace, ep.Address)
			}})
			if errors.Is(err, daemon.ErrRunning) {
				return Reply{}, fmt.Errorf("%w; run se stop --workspace %s first", err, c.Workspace)
			}
			return Reply{}, err
		},
	})
}
