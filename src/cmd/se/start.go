package main

import (
	"encoding/json"
	"fmt"
	"os"
)

func init() {
	register(Command{
		Name:    "start",
		Class:   batch,
		Usage:   "start",
		Group:   "Daemon",
		Summary: "start the daemon in the background, or find it running",
		Details: "answer the running daemon, or start one in the background. Prints its address and token as JSON.",
		Run: func(c *Call) (Reply, error) {
			ep, note, err := startDaemon(&c.World, c.Paths())
			if err != nil {
				return Reply{}, err
			}
			// stdout is the endpoint the plugin reads; the note goes beside it.
			if note != "" {
				fmt.Fprintln(os.Stderr, "se:", note)
			}
			said, err := json.Marshal(ep)
			return Reply{Text: string(said), Endpoint: endpointOf(ep)}, err
		},
	})
}
