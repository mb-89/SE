package issues

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/github"
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
	// Pushed is when the branch last saw a push; zero where GitHub keeps no
	// record of one.
	Pushed time.Time `json:"pushed,omitempty"`
	// Pull is where the branch's open PR stands; nil where it has none.
	Pull *PullState `json:"pull,omitempty"`
	// Base is the branch the issue lands into: its manifest's, or main.
	Base string `json:"base,omitempty"`
	// Foreign is the branch's commits, not on Base, whose subject or merge
	// names another closed issue: work that closed in its own form, whose
	// files the merge takes from Base's side.
	Foreign []Foreign `json:"foreign,omitempty"`
}

// Foreign is a commit on a taken-over branch that names another closed issue.
type Foreign struct {
	SHA     string   `json:"sha"`
	Subject string   `json:"subject"`
	Issue   int      `json:"issue"`
	Files   []string `json:"files"`
}

// PullState is where a takeover's open PR stands, read from GitHub's REST
// API, so the box that takes it over reads it from the take, never from gh.
type PullState struct {
	Number int    `json:"number"`
	URL    string `json:"url"`
	Head   string `json:"head"`
	// Mergeable is GitHub's mergeable_state: clean, dirty, blocked, behind,
	// unstable, or unknown while GitHub has not computed it.
	Mergeable string `json:"mergeable"`
	// Checks is the last run of each check on the PR's head.
	Checks []Check `json:"checks"`
}

// ReadTakeover fills in where took's takeover stands: when its branch was
// last pushed, and its open PR's mergeable state and the last run of each
// of its checks, and the commits on its branch that name another closed
// issue (see foreign). It reads nothing for an issue not taken over.
func (s Source) ReadTakeover(took *Issue) error {
	if took.Takeover == nil {
		return nil
	}
	t := *took.Takeover
	var err error
	if t.Pushed, err = s.lastPush(took.Number); err != nil {
		return err
	}
	open, err := s.openPulls(Branch(took.Number))
	if err != nil {
		return err
	}
	if len(open) > 0 {
		p, err := s.mergeability(open[0])
		if err != nil {
			return err
		}
		runs, err := s.checkRuns(p.Head.SHA)
		if err != nil {
			return err
		}
		state := p.State
		if state == "" {
			state = "unknown"
		}
		t.Pull = &PullState{Number: p.Number, URL: p.URL, Head: p.Head.SHA, Mergeable: state, Checks: runs}
	}
	if t.Base, t.Foreign, err = s.foreign(took.Number); err != nil {
		return err
	}
	took.Takeover = &t
	return nil
}

// named finds the issues a commit subject names: #N, or a branch issue-N.
var named = regexp.MustCompile(`(?:#|\bissue-)(\d+)\b`)

// foreign reads issue n's base (its manifest's branch, or main) and the
// commits on its branch not on the base whose subject names another issue
// that has closed, with the files each touched; the base's own issue and n
// are not another.
func (s Source) foreign(n int) (string, []Foreign, error) {
	top, err := s.manifestOf(n)
	if err != nil {
		return "", nil, err
	}
	base := "main"
	if top != 0 {
		base = Branch(top)
	}
	got, err := api[struct {
		Commits []struct {
			SHA    string `json:"sha"`
			Commit struct {
				Message string `json:"message"`
			} `json:"commit"`
		} `json:"commits"`
	}](s, fmt.Sprintf("repos/%s/compare/%s...%s?per_page=100", s.Repo, base, Branch(n)), false)
	if github.Status(err) == 404 {
		return base, nil, nil
	}
	if err != nil {
		return "", nil, err
	}
	var cands []Foreign
	for _, c := range got[0].Commits {
		subject, _, _ := strings.Cut(c.Commit.Message, "\n")
		for _, m := range named.FindAllStringSubmatch(subject, -1) {
			if k, _ := strconv.Atoi(m[1]); k != n && k != top {
				cands = append(cands, Foreign{SHA: c.SHA, Subject: subject, Issue: k})
				break
			}
		}
	}
	closed, err := each(len(cands), func(k int) (bool, error) {
		i, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, cands[k].Issue), false)
		if github.Status(err) == 404 {
			return false, nil
		}
		return err == nil && i[0].State == "closed", err
	})
	if err != nil {
		return "", nil, err
	}
	var out []Foreign
	for k, f := range cands {
		if closed[k] {
			out = append(out, f)
		}
	}
	files, err := each(len(out), func(k int) ([]string, error) {
		c, err := api[struct {
			Files []struct {
				Name string `json:"filename"`
			} `json:"files"`
		}](s, fmt.Sprintf("repos/%s/commits/%s", s.Repo, out[k].SHA), false)
		if err != nil {
			return nil, err
		}
		names := []string{}
		for _, f := range c[0].Files {
			names = append(names, f.Name)
		}
		return names, nil
	})
	for k := range out {
		out[k].Files = files[k]
	}
	return base, out, err
}

// Line says where a takeover's branch and PR stand, in one line.
func (t Takeover) Line(branch string) string {
	pushed := "GitHub keeps no record of a push to " + branch
	if !t.Pushed.IsZero() {
		pushed = "last pushed to " + branch + " at " + t.Pushed.UTC().Format(time.RFC3339)
	}
	if t.Pull == nil {
		return fmt.Sprintf("Where it stands: no open PR from %s; %s.", branch, pushed)
	}
	checks := "no check ran on its head"
	if len(t.Pull.Checks) > 0 {
		var each []string
		for _, c := range t.Pull.Checks {
			state := c.Conclusion
			if c.Status != "completed" {
				state = c.Status
			}
			each = append(each, c.Name+" "+state)
		}
		sort.Strings(each)
		checks = "its checks' last runs: " + strings.Join(each, ", ")
	}
	return fmt.Sprintf("Where it stands: PR #%d is %s at %s; %s; %s.", t.Pull.Number, t.Pull.Mergeable, t.Pull.Head, checks, pushed)
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
// again shortly, and is no conflict while it stays null. A leaf whose branch
// saw a push within the lease is refused, and its PR not asked: a live box
// works it, and taking it over too would do its work twice.
func (s Source) conflicts(all []Status, pulls []openPull) ([]conflict, error) {
	claimed := map[string]Status{}
	for _, st := range all {
		if st.claimed && !s.live(st) {
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

// live says whether a claimed leaf's branch saw a push within the lease;
// a branch GitHub keeps no record of a push to is not live.
func (s Source) live(st Status) bool {
	return !st.pushed.IsZero() && s.now().Sub(st.pushed) <= Lease
}

// dirty says whether the PR conflicts with its base.
func (p openPull) dirty() bool { return p.Mergeable != nil && !*p.Mergeable && p.State == "dirty" }

// takeOverConflict takes over the first conflict it can, lowest number
// first, and checks its branch out in dir. A conflict on a branch pushed to
// within the lease is refused (see conflicts), and the take moves on. A
// conflict whose last takeover found the same PR head is still in flight
// and is left to its box. A conflict is no failure of its box, as main moves
// on under it: a conflict at a new head is taken over again, final or not,
// and the takeover leaves the issue as final as it was. ok is false when none was taken over.
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
