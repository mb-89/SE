package issues

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// PersonLabel takes an issue out of the queue: it waits for a person, the
// repository's owner, who is assigned to it.
const PersonLabel = "se-person"

// Takeover is a claimed issue's PR that conflicted with main, taken over by
// this box: its branch is checked out as it stands, and the box merges
// origin/main into it, resolves the conflict and lands it again.
type Takeover struct {
	PR  int    `json:"pr"`
	URL string `json:"url"`
	// Count is which takeover of the issue this is, from its marker.
	Count int `json:"count"`
	// Why is what was stuck: "PR #70 conflicts with main", or a finding of
	// se fleet check.
	Why string `json:"why"`
}

// takeoverMark counts an issue's takeovers across boxes; stuck work writes the
// same marker. headMark is the PR head a conflict takeover found, so a box
// tells a takeover still in flight from a second conflict.
var (
	takeoverMark = regexp.MustCompile(`<!-- se:takeover (\d+) -->`)
	headMark     = regexp.MustCompile(`<!-- se:takeover-head ([0-9a-f]+) -->`)
)

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
			pause()
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

func (c conflict) why() string { return fmt.Sprintf("PR #%d conflicts with main", c.pr.Number) }

// comment is the part of an issue comment a takeover reads.
type comment struct {
	ID      int64     `json:"id"`
	Body    string    `json:"body"`
	Created time.Time `json:"created_at"`
}

// marks is what issue n's comments say of its takeovers.
type marks struct {
	// count is how many takeovers it has had (the highest marker).
	count int
	// head is the commit the last takeover found, and at when it was written.
	head     string
	at       time.Time
	comments []comment
}

// takeovers reads issue n's comments for its takeovers.
func (s Source) takeovers(n int) (marks, error) {
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return marks{}, err
	}
	m := marks{comments: comments}
	for _, c := range comments {
		for _, t := range takeoverMark.FindAllStringSubmatch(c.Body, -1) {
			if k, _ := strconv.Atoi(t[1]); k > m.count {
				m.count, m.head, m.at = k, "", c.Created
				if h := headMark.FindStringSubmatch(c.Body); h != nil {
					m.head = h[1]
				}
			}
		}
	}
	return m, nil
}

// takeOver takes over the first conflict it can, lowest number first, and
// checks its branch out in dir. A conflict whose last takeover found the same
// PR head is still in flight and is left to its box; a conflict on an issue
// taken over before goes to a person. ok is false when none was taken over.
func (s Source) takeOver(dir string, all []Status) (took Issue, ok bool, err error) {
	cs, err := s.conflicts(all)
	if err != nil {
		return Issue{}, false, err
	}
	for _, c := range cs {
		m, err := s.takeovers(c.Number)
		if err != nil {
			return Issue{}, false, err
		}
		if m.head == c.pr.Head.SHA {
			continue
		}
		if m.count > 0 {
			if err := s.toPerson(c.Number, c.pr.Head.SHA, c.why(), m.count+1); err != nil {
				return Issue{}, false, err
			}
			continue
		}
		t := &Takeover{PR: c.pr.Number, URL: c.pr.URL, Count: 1, Why: c.why()}
		if took, ok, err = s.takeOverAt(dir, c.Issue, c.pr.Head.SHA, t); err != nil || ok {
			return took, ok, err
		}
	}
	return Issue{}, false, nil
}

// takeOverAt writes takeover t of issue i, found at commit head, and checks
// its branch out in dir as it stands; ok is false where another box wrote the
// same takeover first.
func (s Source) takeOverAt(dir string, i Issue, head string, t *Takeover) (took Issue, ok bool, err error) {
	won, err := s.markTakeover(i.Number, head, t.Why, t.Count)
	if err != nil || !won {
		return Issue{}, false, err
	}
	if err := pickUp(dir, i.Number); err != nil {
		return Issue{}, false, err
	}
	i.Takeover = t
	return i, true, nil
}

// markTakeover writes takeover k on the issue. Where two boxes write the same
// k at once, the first comment wins and the other box withdraws its own.
func (s Source) markTakeover(n int, head, why string, k int) (won bool, err error) {
	path := fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n)
	body := fmt.Sprintf("Taken over: %s at %s. This box merges main into %s, makes it green and lands it again.\n\n<!-- se:takeover %d -->\n<!-- se:takeover-head %s -->",
		why, head, Branch(n), k, head)
	out, err := s.GH("api", "-X", "POST", "-f", "body="+body, path)
	if err != nil {
		return false, fmt.Errorf("recording the takeover of #%d: %w", n, err)
	}
	var mine comment
	if err := json.Unmarshal(out, &mine); err != nil || mine.ID == 0 {
		return false, fmt.Errorf("gh api %s answered no comment: %v", path, err)
	}
	m, err := s.takeovers(n)
	if err != nil {
		return false, err
	}
	first := mine.ID
	for _, o := range m.comments {
		for _, m := range takeoverMark.FindAllStringSubmatch(o.Body, -1) {
			if m[1] == strconv.Itoa(k) && o.ID < first {
				first = o.ID
			}
		}
	}
	if first == mine.ID {
		return true, nil
	}
	if _, err := s.GH("api", "-X", "DELETE", fmt.Sprintf("repos/%s/issues/comments/%d", s.Repo, mine.ID)); err != nil {
		return false, fmt.Errorf("withdrawing a second takeover of #%d: %w", n, err)
	}
	return false, nil
}

// toPerson takes issue n out of the queue: it is labelled se-person and
// assigned to the repository's owner, with takeover k, found at head, recorded.
func (s Source) toPerson(n int, head, why string, k int) error {
	owner, _, _ := strings.Cut(s.Repo, "/")
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	body := fmt.Sprintf("Stuck again: %s, after %d takeover(s), so it waits for a person: labelled %s and assigned to @%s.\n\n<!-- se:takeover %d -->\n<!-- se:takeover-head %s -->",
		why, k-1, PersonLabel, owner, k, head)
	for _, args := range [][]string{
		{"api", "-X", "POST", "-f", "body=" + body, path + "/comments"},
		{"api", "-X", "POST", "-f", "labels[]=" + PersonLabel, path + "/labels"},
		{"api", "-X", "POST", "-f", "assignees[]=" + owner, path + "/assignees"},
	} {
		if _, err := s.GH(args...); err != nil {
			return fmt.Errorf("handing #%d to a person: %w", n, err)
		}
	}
	return nil
}
