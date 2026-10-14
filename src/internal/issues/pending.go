package issues

import "sort"

// Pending is one thing that waits on the person, as se briefing lists it.
type Pending struct {
	// Source says what found it; one source is left, "waiting on a person".
	Source string `json:"source"`
	Number int    `json:"number"`
	Title  string `json:"title"`
	URL    string `json:"url"`
	// Reason says why it waits on the person.
	Reason string `json:"reason"`
	// Holds counts the open fleet issues it holds up.
	Holds int `json:"holds"`
}

// pending is what waits on the person: every open issue labelled se-person,
// with what it holds up, lowest number first.
func pending(ws []Waiting) []Pending {
	out := []Pending{}
	for _, w := range ws {
		out = append(out, Pending{Source: "waiting on a person", Number: w.Number, Title: w.Title, URL: w.URL, Reason: w.Reason, Holds: w.Blocks})
	}
	sort.SliceStable(out, func(a, b int) bool { return out[a].Number < out[b].Number })
	return out
}
