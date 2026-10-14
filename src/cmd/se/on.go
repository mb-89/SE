package main

import (
	"fmt"
	"time"
)

// The longest the session waits for a starting daemon.
const startWait = 10 * time.Second

func init() {
	register(Command{
		Name:      "on",
		Usage:     "on",
		Group:     "Session",
		Summary:   "switch SE on: start the daemon, forward this session's events",
		Details:   "switch SE on: start this workspace's daemon and forward every event of the session to it.",
		Session:   true,
		Installed: true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("on")); err != nil {
				return Reply{}, err
			}
			reply := Reply{Active: switched(true)}
			ep, note, err := startDaemon(c.Paths(), c.Clock, c.Net)
			if err != nil {
				reply.Text = joined(fmt.Sprintf("SE is on, but its daemon did not start: %v. Events pass unlogged until it does.", err), note)
				return reply, nil
			}
			reply.Endpoint = endpointOf(ep)
			reply.Text = joined(fmt.Sprintf("SE is on. Every event of this session is logged under %s.", c.Paths().Logs()), note)
			return reply, nil
		},
	})
}
