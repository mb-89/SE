package main

import (
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
)

func init() {
	register(Command{
		Name:    "stop",
		Usage:   "stop",
		Group:   "Daemon",
		Summary: "end this workspace's daemon",
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("stop")); err != nil {
				return Reply{}, err
			}
			return Reply{}, daemon.Stop(c.Paths(), 5*time.Second, c.Clock)
		},
	})
}
