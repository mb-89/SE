package main

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/update"
)

func init() {
	register(Command{
		Name:      "update",
		Class:     batch,
		Usage:     "update [--repo DIR] [--session-start]",
		Group:     "Session",
		Summary:   "pull main into the installed SE, rebuild se and reload",
		Details:   "pull main into the installed SE checkout, rebuild se, restart a running daemon and reload the plugin.",
		Session:   true,
		Installed: true,
		Button:    true,
		Flags: []index.Flag{
			{Name: "repo", Default: "", Help: "the installed SE checkout `DIR` (default: the one this binary was built into)"},
			// The plugin updates its own checkout as a session starts: nothing
			// there may fail the session, and an update that changed nothing is silent.
			{Name: "session-start", Default: false, Help: "as the plugin runs it at session start: never fail, say nothing when nothing changed"},
		},
		Run: func(c *Call) (Reply, error) {
			repo, start := c.Args.String("repo"), c.Args.Bool("session-start")
			// The path is read before the update renames this binary away.
			exe, err := c.Proc.Self()
			if err != nil {
				return Reply{}, err
			}
			if repo == "" {
				// se is built to <checkout>/src/plugin/bin/se.
				repo = filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(exe))))
			}
			r, err := update.Run(c.Disk, c.Proc, c.Git, repo, exe)
			var untouched *update.Untouched
			switch {
			case err == nil:
			case !start:
				return Reply{}, err
			case errors.As(err, &untouched):
				return Reply{Text: fmt.Sprintf("SE left its checkout as it is: %s.", oneLine(err))}, nil
			default:
				return Reply{Text: fmt.Sprintf("SE did not update %s, so the session goes on with the SE it has: %s", repo, oneLine(err))}, nil
			}
			if start && r.From == r.To {
				return Reply{}, nil
			}
			reply := Reply{Text: fmt.Sprintf("SE updated %s → %s.", r.From, r.To), Reload: reloads(c)}
			if r.From == r.To {
				return Reply{Text: fmt.Sprintf("SE is at the newest main already (%s).", r.To)}, nil
			}
			// A running daemon runs the old se until it starts again.
			if _, running := daemon.Healthy(c.Paths(), c.Net); !running {
				return reply, nil
			}
			if err := daemon.Stop(c.Paths(), 5*time.Second, c.Clock, c.Net); err != nil {
				return reply, fmt.Errorf("updated %s → %s, but the old daemon did not stop: %w", r.From, r.To, err)
			}
			ep, note, err := startDaemon(&c.World, c.Paths())
			if err != nil {
				reply.Text = joined(reply.Text+fmt.Sprintf(" The daemon did not start again: %v.", err), note)
				return reply, nil
			}
			reply.Endpoint = endpointOf(ep)
			reply.Text = joined(reply.Text+" Its daemon restarted.", note)
			return reply, nil
		},
	})
}

// remoteEnv is set to true in a session reached over a remote connection,
// such as a cloud box, where /reload-plugins is refused.
const remoteEnv = "CLAUDE_CODE_REMOTE"

// reloads says whether an update asks the plugin to reload: only in a
// session, and never over a remote connection, which refuses the reload and
// says so in the transcript. The new se runs at once there anyway.
func reloads(c *Call) bool { return c.Session && c.Getenv(remoteEnv) != "true" }

// oneLine folds an error's lines into one.
func oneLine(err error) string { return strings.Join(strings.Fields(err.Error()), " ") }
