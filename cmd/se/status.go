package main

import (
	"fmt"
	"time"

	"github.com/mb-89/SE/internal/daemon"
)

func init() {
	register(Command{
		Name:    "status",
		Usage:   "status",
		Group:   "Session",
		Summary: "say whether a daemon answers for this workspace",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("status")); err != nil {
				return Reply{}, err
			}
			ep, ok := daemon.Healthy(c.Paths())
			if !ok {
				return Reply{Text: fmt.Sprintf("No SE daemon answers for %s.", c.Workspace)}, nil
			}
			return Reply{Text: fmt.Sprintf("SE's daemon answers for %s at %s (pid %d, up since %s).",
				c.Workspace, ep.Address, ep.PID, ep.StartedAt.Local().Format(time.DateTime))}, nil
		},
	})
}
