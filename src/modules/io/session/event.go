// Package session holds the session event log's two I/O modules and the log
// folder they keep: Posts commits each event the plugin's bridgehead
// forwards, and the log module reads those events and writes each as one line
// of its session's log. Code that writes the log takes a Log as an argument;
// the daemon hands it Folder, a test hands it a Fake.
package session

import (
	"encoding/json"
	"regexp"
	"strings"
)

// PayloadCap is the longest event input a row carries whole; a longer one lands cut.
const PayloadCap = 4000

var name = regexp.MustCompile(`^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$`)

// Named says whether s can name a session: a file name that stays in the log folder.
func Named(s string) bool { return name.MatchString(s) }

// Event is one session event as the bridgehead forwarded it.
type Event struct {
	// Seq numbers the events in the order the daemon took them, from 1; the
	// built-in Event, 0, is no event.
	Seq     uint64          `json:"-"`
	Session string          `json:"session"`
	Event   string          `json:"event"`
	At      string          `json:"at"`
	E       json.RawMessage `json:"e"`
}

// Row is the event as its log carries it: one JSON line, its input whole
// while short, else its head and length.
func Row(ev Event) ([]byte, error) {
	return json.Marshal(map[string]any{"at": ev.At, "event": ev.Event, "e": payloadOf(ev.E)})
}

func payloadOf(raw json.RawMessage) any {
	if len(raw) == 0 {
		return nil
	}
	if len(raw) <= PayloadCap {
		return raw
	}
	return map[string]any{"cut": true, "length": len(raw), "head": strings.ToValidUTF8(string(raw[:PayloadCap]), "")}
}
