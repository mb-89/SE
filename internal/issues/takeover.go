package issues

import (
	"fmt"
	"sort"
	"time"
)

// Takeover is a claimed leaf taken over by this box: its branch is checked
// out as it stands. Either its PR conflicted with main, and the box merges
// origin/main into it, resolves the conflict and lands it again; or it was
// stuck (Stale says how), and the box continues the work.
type Takeover struct {
	// PR is the conflicting PR; 0 for stuck work.
	PR  int    `json:"pr,omitempty"`
	URL string `json:"url,omitempty"`
	// Count is which takeover of the issue this is, from its marker.
	Count int `json:"count"`
	// Stale says what made the claim stuck: nothing pushed for how long.
	Stale string `json:"stale,omitempty"`
}

// pause is the wait before asking GitHub again for a mergeability it has not
// computed yet; tests make it nothing.
var pause = func() { time.Sleep(3 * time.Second) }

// asks is how often a PR's mergeability is asked for before a null answer is
// taken as no conflict.
const asks = 3

// openPull is the part of GitHub's pull request object a takeover reads.
type openPull struct {
	Number    int    `json:"number"`
	URL       string `json:"html_url"`
	Mergeable *bool  `json:"mergeable"`
	State     string `json:"mergeable_state"`
	Head      struct {
		Ref string `json:"ref"`
		SHA string `json:"sha"`
	} `json:"head"`
}

// conflict is a claimed leaf whose open PR GitHub reports in conflict with main.
type conflict struct {
	Status
	pr openPull
}

// conflicts names the claimed leaves whose open PR is not mergeable
// (mergeable_state dirty), lowest number first. A null mergeable is asked
// again shortly, and is no conflict while it stays null.
func (s Source) conflicts(all []Status) ([]conflict, error) {
	claimed := map[string]Status{}
	for _, st := range all {
		if st.claimed {
			claimed[Branch(st.Number)] = st
		}
	}
	if len(claimed) == 0 {
		return nil, nil
	}
	pulls, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls?base=main&state=open&per_page=100", s.Repo), true)
	if err != nil {
		return nil, err
	}
	var out []conflict
	for _, p := range pulls {
		st, ok := claimed[p.Head.Ref]
		if !ok {
			continue
		}
		for k := 0; k < asks; k++ {
			if k > 0 {
				pause()
			}
			got, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls/%d", s.Repo, p.Number), false)
			if err != nil {
				return nil, err
			}
			if p = got[0]; p.Mergeable != nil {
				break
			}
		}
		if p.Mergeable != nil && !*p.Mergeable && p.State == "dirty" {
			out = append(out, conflict{st, p})
		}
	}
	sort.Slice(out, func(a, b int) bool { return out[a].Number < out[b].Number })
	return out, nil
}

// takeOverConflict takes over the first conflict it can, lowest number
// first, and checks its branch out in dir. A conflict whose last takeover
// found the same PR head is still in flight and is left to its box; a
// conflict on an issue taken over before goes to a person. ok is false when
// none was taken over.
func (s Source) takeOverConflict(dir string, all []Status) (took Issue, ok bool, err error) {
	cs, err := s.conflicts(all)
	if err != nil {
		return Issue{}, false, err
	}
	for _, c := range cs {
		m, err := s.marks(c.Number)
		if err != nil {
			return Issue{}, false, err
		}
		if m.head == c.pr.Head.SHA {
			continue
		}
		k := m.takeovers + 1
		heads := fmt.Sprintf("\n\n<!-- se:takeover %d -->\n<!-- se:takeover-head %s -->", k, c.pr.Head.SHA)
		if m.takeovers > 0 {
			reason := fmt.Sprintf("PR #%d conflicts with main again: it was taken over %s already, so it waits for a person. "+
				"`se issue resume %d` puts it back in the queue.", c.pr.Number, times(m.takeovers), c.Number)
			if err := s.flag(c.Issue, reason, heads); err != nil {
				return Issue{}, false, err
			}
			continue
		}
		body := fmt.Sprintf("Taken over: PR #%d conflicts with main at %s. This box merges main into %s and lands it again.",
			c.pr.Number, c.pr.Head.SHA, Branch(c.Number)) + heads
		won, err := s.markTakeover(c.Number, k, body)
		if err != nil {
			return Issue{}, false, err
		}
		if !won {
			continue
		}
		if err := pickUp(dir, c.Number); err != nil {
			return Issue{}, false, err
		}
		took = c.Issue
		took.Takeover = &Takeover{PR: c.pr.Number, URL: c.pr.URL, Count: k}
		return took, true, nil
	}
	return Issue{}, false, nil
}
