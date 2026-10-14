package issues

import (
	"fmt"
	"strings"
	"time"
)

// PersonLine is the line the body of a run's controversial finding opens
// with: it waits for a person (se-person, assigned to the owner).
const PersonLine = "Controversial, so it waits for a person"

// Released says that the owner released an issue filed for a person to the
// boxes: its body still opens with PersonLine, but it no longer carries
// se-person. By and At are who took the label off and when, where GitHub's
// events name it.
type Released struct {
	By string    `json:"by,omitempty"`
	At time.Time `json:"at,omitempty"`
}

// Line says so to the box that took it, so it need not guess.
func (r Released) Line() string {
	who := "the owner"
	if r.By != "" {
		who = "@" + r.By
	}
	when := ""
	if !r.At.IsZero() {
		when = " at " + r.At.UTC().Format("2006-01-02 15:04 UTC")
	}
	return fmt.Sprintf("Released to the boxes: %s took %s off%s. Its body still says it waits for a person; that no longer holds, so do it.", who, PersonLabel, when)
}

// event is the part of GitHub's issue event the release reads.
type event struct {
	Event string `json:"event"`
	Actor struct {
		Login string `json:"login"`
	} `json:"actor"`
	Label struct {
		Name string `json:"name"`
	} `json:"label"`
	Created time.Time `json:"created_at"`
}

// Release answers whether i, which a take handed over, was filed for a
// person and released by the owner: its body opens with PersonLine, and as
// it was taken, it no longer carries se-person. Who took the label off, and
// when, come from the issue's events; where they cannot be read, the release
// stands without them.
func (s Source) Release(i Issue) *Released {
	if !strings.HasPrefix(strings.TrimSpace(i.Body), PersonLine) {
		return nil
	}
	r := &Released{}
	events, err := pages[event](s, fmt.Sprintf("repos/%s/issues/%d/events?per_page=%d", s.Repo, i.Number, PerPage))
	if err != nil {
		return r
	}
	for _, e := range events {
		if e.Event == "unlabeled" && e.Label.Name == PersonLabel && !e.Created.Before(r.At) {
			r.By, r.At = e.Actor.Login, e.Created
		}
	}
	return r
}
