package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
)

func init() {
	register(Command{
		Name:    "status",
		Class:   interactive,
		Usage:   "status",
		Group:   "Session",
		Summary: "say whether a daemon answers, and which commits SE came from",
		Details: "say whether a daemon answers for this workspace, and which commits the session's SE came from: one line where the hooks, the plugin's checkout and se agree; where they disagree, a short line per commit and the remedy, a new session, once.",
		Session: true,
		Button:  true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("status")); err != nil {
				return Reply{}, err
			}
			said := fmt.Sprintf("No SE daemon answers for %s.", c.Workspace)
			if ep, ok := daemon.Healthy(c.Paths(), c.Net); ok {
				said = fmt.Sprintf("SE's daemon answers for %s at %s (pid %d, up since %s).",
					c.Workspace, ep.Address, ep.PID, ep.StartedAt.Local().Format(time.DateTime))
			}
			// One line where everything agrees; a short line per commit where not.
			sep := "\n"
			commits := sessionCommits(&c.World)
			if !strings.Contains(commits, "\n") {
				sep = " "
			}
			return Reply{Text: said + sep + commits}, nil
		},
	})
}
