package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
)

func init() {
	register(Command{
		Name:      "restart",
		Class:     batch,
		Usage:     "restart",
		Group:     "Session",
		Summary:   "restart the daemon; in an SE checkout, rebuild se first",
		Details:   "stop this workspace's daemon and start it again. In an SE checkout, se is rebuilt from its source first.",
		Session:   true,
		Installed: true,
		Button:    true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("restart")); err != nil {
				return Reply{}, err
			}
			// No other start runs meanwhile; this one is a try, too.
			held, err := starting(c.Paths(), c.Clock)
			if err != nil {
				return Reply{}, err
			}
			defer held.Close()
			if err := tries(c.Paths(), c.Clock); err != nil {
				return Reply{}, err
			}
			// The build runs while the old daemon still serves.
			exe, note, err := daemonExe(&c.World, c.Paths())
			if err != nil {
				return Reply{}, err
			}
			if err := daemon.Stop(c.Paths(), 5*time.Second, c.Clock, c.Net); err != nil {
				return Reply{}, fmt.Errorf("the running daemon did not stop: %w", err)
			}
			ep, err := daemon.Start(c.Proc, c.Paths(), exe, startWait, c.Clock, c.Net)
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
