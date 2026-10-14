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
	// Answers is the answers file the take wrote back from the issue's last
	// landing comment (see RestoreAnswers); empty where it wrote none.
	Answers string `json:"answers,omitempty"`
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
	Base struct {
		Ref string `json:"ref"`
	} `json:"base"`
}

// toMain is the open PRs into main, by their head branch.
func toMain(pulls []openPull) map[string]openPull {
	byRef := map[string]openPull{}
	for _, p := range pulls {
		if p.Base.Ref == "main" {
			byRef[p.Head.Ref] = p
		}
	}
	return byRef
}

// conflict is a claimed leaf whose open PR GitHub reports in conflict with main.
type conflict struct {
	Status
	pr openPull
}

// conflicts names the claimed leaves whose open PR is not mergeable
// (mergeable_state dirty), lowest number first. A null mergeable is asked
// again shortly, and is no conflict while it stays null.
func (s Source) conflicts(all []Status, pulls []openPull) ([]conflict, error) {
	claimed := map[string]Status{}
	for _, st := range all {
		if st.claimed {
			claimed[Branch(st.Number)] = st
		}
	}
	if len(claimed) == 0 {
		return nil, nil
	}
	var mine []openPull
	for _, p := range pulls {
		if _, ok := claimed[p.Head.Ref]; ok && p.Base.Ref == "main" {
			mine = append(mine, p)
		}
	}
	asked, err := each(len(mine), func(k int) (openPull, error) { return s.mergeability(mine[k]) })
	if err != nil {
		return nil, err
	}
	var out []conflict
	for _, p := range asked {
		if p.dirty() {
			out = append(out, conflict{claimed[p.Head.Ref], p})
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
			s.sleep(pause, fmt.Sprintf("GitHub to compute whether PR #%d merges (ask %d of %d)", p.Number, k+1, asks))
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
// found the same PR head is still in flight and is left to its box. A
// conflict is no failure (main moves while a PR waits), so a conflict
// takeover never makes an issue final, and a final issue in conflict is
// taken over like any other. ok is false when none was taken over.
func (s Source) takeOverConflict(dir string, all []Status, pulls []openPull) (took Issue, ok bool, err error) {
	cs, err := s.conflicts(all, pulls)
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
		body := fmt.Sprintf("Taken over: PR #%d conflicts with main at %s. This box merges main into %s and lands it again.",
			c.pr.Number, c.pr.Head.SHA, Branch(c.Number)) + heads + s.boxLine()
		won, err := s.markTakeover(c.Number, k, body)
		if err != nil {
			return Issue{}, false, err
		}
		if !won {
			continue
		}
		if err := s.pickUp(dir, c.Number); err != nil {
			return Issue{}, false, err
		}
		took = c.Issue
		took.Takeover = &Takeover{PR: c.pr.Number, URL: c.pr.URL, Count: k}
		return took, true, nil
	}
	return Issue{}, false, nil
}
