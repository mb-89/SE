package main

import (
	"fmt"
	"time"

	"github.com/mb-89/SE/internal/daemon"
)

// The longest the session waits for a starting daemon.
const startWait = 10 * time.Second

func init() {
	register(Command{
		Name:    "on",
		Usage:   "on",
		Summary: "switch SE on: start this workspace's daemon and forward every event of the session to it",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("on")); err != nil {
				return Reply{}, err
			}
			reply := Reply{Active: switched(true)}
			exe, err := executable()
			if err != nil {
				return Reply{}, err
			}
			ep, err := daemon.Start(c.Paths(), exe, startWait)
			if err != nil {
				reply.Text = fmt.Sprintf("SE is on, but its daemon did not start: %v. Events pass unlogged until it does.", err)
				return reply, nil
			}
			reply.Endpoint = endpointOf(ep)
			reply.Text = fmt.Sprintf("SE is on. Every event of this session is logged under %s.", c.Paths().Logs())
			return reply, nil
		},
	})
}
