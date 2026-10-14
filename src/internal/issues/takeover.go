package issues

import (
	"encoding/json"
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
// computed yet.
const pause = 3 * time.Second

// asks is how often a PR's mergeability is asked for before a null answer is
// taken as no conflict.
const asks = 3

// openPull is the part of GitHub's pull request object a takeover reads.
type openPull struct {
	Number    int    `json:"number"`
	URL       string `json:"html_url"`
	Mergeable *bool  `json:"mergeable"`
	State     string `json:"mergeable_state"`
	// AutoMerge is GitHub's auto-merge request; null while auto-merge is off.
	AutoMerge *json.RawMessage `json:"auto_merge"`
	NodeID    string           `json:"node_id"`
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
		if p, err = s.mergeability(p); err != nil {
			return nil, err
		}
		if p.dirty() {
			out = append(out, conflict{st, p})
		}
	}
	sort.Slice(out, func(a, b int) bool { return out[a].Number < out[b].Number })
	return out, nil
}

// mergeability asks GitHub for the PR until it has computed whether it
// merges, asks times at most.
func (s Source) mergeability(p openPull) (openPull, error) {
	for k := 0; k < asks; k++ {
		if k > 0 {
			s.Clock.Sleep(pause)
		}
		got, err := api[openPull](s, fmt.Sprintf("repos/%s/pulls/%d", s.Repo, p.Number), false)
		if err != nil {
			return openPull{}, err
		}
		if p = got[0]; p.Mergeable != nil {
			break
		}
	}
	return p, nil
}

// dirty says whether the PR conflicts with its base.
func (p openPull) dirty() bool { return p.Mergeable != nil && !*p.Mergeable && p.State == "dirty" }

// takeOverConflict takes over the first conflict it can, lowest number
// first, and checks its branch out in dir. A conflict whose last takeover
// found the same PR head is still in flight and is left to its box; a
// conflict on a final issue (one taken over before, or filed by a review)
// waits on an issue for a person. A takeover labels the issue se-final. ok is false when none was
// taken over.
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
		if c.Final {
			reason := fmt.Sprintf("PR #%d conflicts with main on its final attempt (labelled %s).", c.pr.Number, FinalLabel)
			if _, err := s.hold(c.Issue, reason); err != nil {
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
		if err := s.finalize(c.Number); err != nil {
			return Issue{}, false, err
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
