package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/mb-89/SE/internal/daemon"
)

func init() {
	register(Command{
		Name:      "restart",
		Usage:     "restart",
		Group:     "Session",
		Summary:   "restart the daemon; in an SE checkout, rebuild se first",
		Details:   "stop this workspace's daemon and start it again. In an SE checkout, se is rebuilt from its source first.",
		Session:   true,
		Installed: true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("restart")); err != nil {
				return Reply{}, err
			}
			// The build runs while the old daemon still serves.
			exe, note, err := daemonExe(c.Paths())
			if err != nil {
				return Reply{}, err
			}
			if err := daemon.Stop(c.Paths(), 5*time.Second); err != nil {
				return Reply{}, fmt.Errorf("the running daemon did not stop: %w", err)
			}
			ep, err := daemon.Start(c.Paths(), exe, startWait)
			if err != nil {
				return Reply{Text: joined(fmt.Sprintf("SE's daemon stopped but did not start again: %v.", err), note)}, nil
			}
			return Reply{
				Text:     joined(fmt.Sprintf("SE's daemon restarted at %s (pid %d).", ep.Address, ep.PID), note),
				Endpoint: endpointOf(ep),
			}, nil
		},
	})
}

// joined puts a note after a sentence.
func joined(text, note string) string { return strings.TrimSpace(text + " " + note) }
