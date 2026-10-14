package main

import (
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
)

func init() {
	register(Command{
		Name:    "stop",
		Class:   batch,
		Usage:   "stop",
		Group:   "Daemon",
		Summary: "end this workspace's daemon",
		Run: func(c *Call) (Reply, error) {
			return Reply{}, daemon.Stop(c.Paths(), 5*time.Second, c.Clock, c.Net)
		},
	})
}
