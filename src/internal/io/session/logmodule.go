package session

import "github.com/mb-89/SE/src/internal/index"

type logIn struct {
	Events Event `index:"events"`
}

// LogModule is the session log on the index: an I/O module that reads each
// session event, at the session it came from where events is wired to a
// family, and writes it as one line of its session's log in l, its one
// outside thing. Its output is the number of the last event it wrote.
func LogModule(l Log) *index.Module {
	return index.Declare("sessionlog", "The session log: one line per session event, one log per session.",
		index.IO(),
		index.Derived("written", uint64(0), "The number of the last session event the log wrote.",
			func(in logIn) (uint64, error) {
				ev := in.Events
				if ev.Seq == 0 {
					return 0, nil
				}
				row, err := Row(ev)
				if err != nil {
					return 0, err
				}
				if err := l.Append(ev.Session, row); err != nil {
					return 0, err
				}
				return ev.Seq, nil
			}),
	)
}
