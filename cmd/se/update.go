package main

import (
	"fmt"
	"path/filepath"
	"time"

	"github.com/mb-89/SE/internal/daemon"
	"github.com/mb-89/SE/internal/update"
)

func init() {
	register(Command{
		Name:    "update",
		Usage:   "update [--repo DIR]",
		Summary: "pull main into the installed SE checkout, rebuild se, restart a running daemon and reload the plugin",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs := c.Flags("update")
			repo := fs.String("repo", "", "the installed SE checkout (default: the one this binary was built into)")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			// The path is read before the update renames this binary away.
			exe, err := executable()
			if err != nil {
				return Reply{}, err
			}
			if *repo == "" {
				// se is built to <checkout>/plugin/bin/se.
				*repo = filepath.Dir(filepath.Dir(filepath.Dir(exe)))
			}
			r, err := update.Run(*repo, exe)
			if err != nil {
				return Reply{}, err
			}
			reply := Reply{Text: fmt.Sprintf("SE updated %s → %s.", r.From, r.To), Reload: c.Session}
			if r.From == r.To {
				return Reply{Text: fmt.Sprintf("SE is at the newest main already (%s).", r.To)}, nil
			}
			// A running daemon runs the old se until it starts again.
			if _, running := daemon.Healthy(c.Paths()); !running {
				return reply, nil
			}
			if err := daemon.Stop(c.Paths(), 5*time.Second); err != nil {
				return reply, fmt.Errorf("updated %s → %s, but the old daemon did not stop: %w", r.From, r.To, err)
			}
			ep, err := daemon.Start(c.Paths(), exe, startWait)
			if err != nil {
				reply.Text += fmt.Sprintf(" The daemon did not start again: %v.", err)
				return reply, nil
			}
			reply.Endpoint = endpointOf(ep)
			reply.Text += " Its daemon restarted."
			return reply, nil
		},
	})
}
