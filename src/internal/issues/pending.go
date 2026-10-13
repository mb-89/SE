package issues

import "sort"

// Pending is one thing that waits on the person, as se briefing lists it.
type Pending struct {
	// Source is the name of the source that found it.
	Source string `json:"source"`
	Number int    `json:"number"`
	Title  string `json:"title"`
	URL    string `json:"url"`
	// Reason says why it waits on the person.
	Reason string `json:"reason"`
	// Holds counts the open fleet issues it holds up.
	Holds int `json:"holds"`
}

// Open is what a pending source reads from: one survey of the open fleet
// issues, read once for every source.
type Open struct {
	Repo string
	// Waiting is every open issue labelled se-person, with what it holds up.
	Waiting []Waiting
	t       tree
}

// Labelled says whether open issue n carries the label.
func (o Open) Labelled(n int, label string) bool { return o.t.byNum[n].labelled(label) }

// PendingSource is one source of things that wait on the person. A source
// registers itself from its own file's init, so a new source is one new file
// and se briefing lists it without being told.
type PendingSource struct {
	// Name says what the source finds: "waiting on a person", "report waiting".
	Name string
	// List answers what waits now.
	List func(o Open) ([]Pending, error)
}

var pendingSources []PendingSource

// RegisterPending adds a source of pending items to se briefing.
func RegisterPending(p PendingSource) {
	for _, q := range pendingSources {
		if q.Name == p.Name {
			panic("issues: two pending sources named " + p.Name)
		}
	}
	pendingSources = append(pendingSources, p)
	sort.SliceStable(pendingSources, func(a, b int) bool { return pendingSources[a].Name < pendingSources[b].Name })
}

// pending asks every registered source, in the order of their names, each
// source's items lowest number first.
func pending(o Open) ([]Pending, error) {
	out := []Pending{}
	for _, p := range pendingSources {
		got, err := p.List(o)
		if err != nil {
			return nil, err
		}
		for k := range got {
			got[k].Source = p.Name
		}
		sort.SliceStable(got, func(a, b int) bool { return got[a].Number < got[b].Number })
		out = append(out, got...)
	}
	return out, nil
}
