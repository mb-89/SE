package session

import "github.com/mb-89/SE/src/index"

// Events is the family Posts commits each forwarded event to, at its session's id.
var Events = index.Family("events", Event{}, "The last event the bridgehead forwarded from a session, at the session's id.")

// Posts is the I/O module of the bridgehead's posts: the daemon commits each
// session event the plugin forwards to Events, at its session, and nothing
// else writes it.
var Posts = index.Declare("session", "The session events the plugin's bridgehead forwards.",
	index.IO(),
	Events,
)
