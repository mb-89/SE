package main

import (
	"encoding/json"
	"time"

	"github.com/mb-89/SE/internal/daemon"
)

func init() {
	register(Command{
		Name:    "start",
		Usage:   "start",
		Summary: "answer the running daemon, or start one in the background; prints its address and token as JSON",
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("start")); err != nil {
				return Reply{}, err
			}
			exe, err := executable()
			if err != nil {
				return Reply{}, err
			}
			ep, err := daemon.Start(c.Paths(), exe, 10*time.Second)
			if err != nil {
				return Reply{}, err
			}
			said, err := json.Marshal(ep)
			return Reply{Text: string(said), Endpoint: endpointOf(ep)}, err
		},
	})
}
