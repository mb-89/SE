package session

import "github.com/mb-89/SE/src/internal/index"

// Events is the output Posts commits each forwarded event to.
var Events = index.Output("events", Event{}, "The last session event the bridgehead forwarded.")

// Posts is the I/O module of the bridgehead's posts: the daemon commits each
// session event the plugin forwards to Events, and nothing else writes it.
var Posts = index.Declare("session", "The session events the plugin's bridgehead forwards.",
	index.IO(),
	Events,
)
