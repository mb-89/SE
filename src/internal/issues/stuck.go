package issues

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/github"
)

// Lease is the built-in value of issues/config/lease: how long a claimed leaf may go without a push to its branch before
// it is stuck. It is under the routine's 4-hour schedule, so a scheduled box
// always finds a stuck issue.
const Lease = 3 * time.Hour

// PersonLabel marks an issue that waits on a person, the repository's owner,
// who is assigned to it; no box is offered it, or a tree containing it.
const PersonLabel = "se-person"

// The marks se leaves in the comments it writes, so what it did survives the
// box that did it: <!-- se:takeover 1 -->, and <!-- se:takeover-head abc -->,
// the PR head a conflict takeover found. <!-- se:person --> and
// <!-- se:resume --> are an old hold's, which se no longer writes; they are
// still read, as history.
var mark = regexp.MustCompile(`<!-- se:(takeover|person|resume|takeover-head)(?: ([0-9a-f]+))? -->`)

// comment is the part of GitHub's issue comment object the rules read.
type comment struct {
	ID      int64     `json:"id"`
	Body    string    `json:"body"`
	Created time.Time `json:"created_at"`
	// IssueURL is the API URL of the issue it is on.
	IssueURL string `json:"issue_url"`
}

// marks is what an issue's comments say about it since the last resume
// mark, which only an old hold wrote.
type marks struct {
	// takeovers is the highest takeover round; two boxes racing for one round
	// count once. head is the PR head that round's conflict takeover found,
	// so a box tells a takeover still in flight from a second conflict.
	takeovers    int
	head         string
	lastTakeover time.Time
	// reason is the text of the last person mark.
	reason string
	// winners maps each takeover round to its first comment's id.
	winners map[int]int64
	// box is the session of the box whose claim it is, from the last box mark.
	box string
	// retry is when a fan-out the routine refused for its rate limit, after
	// this claim, may fire again: the last retry mark, zero once one after it
	// says the retry fired.
	retry time.Time
}

func (s Source) marks(n int) (marks, error) {
	all, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return marks{}, err
	}
	return marksOf(all), nil
}

// marksOf reads the marks out of an issue's comments, oldest first.
func marksOf(all []comment) marks {
	m := marks{winners: map[int]int64{}}
	for _, c := range all {
		for _, got := range boxMark.FindAllStringSubmatch(c.Body, -1) {
			m.box = got[1]
		}
		round := 0
		for _, got := range mark.FindAllStringSubmatch(c.Body, -1) {
			switch got[1] {
			case "resume":
				m = marks{winners: map[int]int64{}}
			case "person":
				m.reason = Shown(c.Body)
			case "takeover":
				round, _ = strconv.Atoi(got[2])
				if round > m.takeovers {
					m.takeovers, m.head = round, ""
				}
				if c.Created.After(m.lastTakeover) {
					m.lastTakeover = c.Created
				}
				if id, ok := m.winners[round]; !ok || c.ID < id {
					m.winners[round] = c.ID
				}
			case "takeover-head":
				if round == m.takeovers {
					m.head = got[2]
				}
			}
		}
		for _, got := range fanoutMark.FindAllStringSubmatch(c.Body, -1) {
			if got[1] == "fired" {
				m.retry = time.Time{}
			} else if at, err := time.Parse(time.RFC3339, got[2]); err == nil {
				m.retry = at
			}
		}
	}
	return m
}

// lastPush is when issue n's branch last saw a push, its creation included;
// zero where GitHub keeps no record of one.
func (s Source) lastPush(n int) (time.Time, error) {
	got, err := api[[]struct {
		Timestamp time.Time `json:"timestamp"`
	}](s, fmt.Sprintf("repos/%s/activity?ref=refs/heads/%s&per_page=1", s.Repo, Branch(n)), false)
	if err != nil {
		return time.Time{}, err
	}
	var last time.Time
	for _, a := range got[0] {
		if a.Timestamp.After(last) {
			last = a.Timestamp
		}
	}
	return last, nil
}

// quiet is the one rule for when a claim has stopped moving, which the lease
// (stuck, with the lease as window) and se fleet check (with Quiet) both
// read: nothing pushed to issue n's branch since pushed, nor a takeover of
// it recorded, for longer than window. n's comments are read only where the
// push is that old; moved is when the claim last moved, its push or its last
// takeover, and m the marks read, nil where none were.
func (s Source) quiet(n int, pushed time.Time, window time.Duration) (quiet bool, moved time.Time, m *marks, err error) {
	if s.now().Sub(pushed) <= window {
		return false, pushed, nil, nil
	}
	got, err := s.marks(n)
	if err != nil {
		return false, pushed, nil, err
	}
	moved = pushed
	if got.lastTakeover.After(moved) {
		moved = got.lastTakeover
	}
	return s.now().Sub(moved) > window, moved, &got, nil
}

// lease reads whether a claimed leaf is stuck: quiet for longer than the
// lease.
func (s Source) lease(st *Status) error {
	pushed, err := s.lastPush(st.Number)
	if err != nil {
		return err
	}
	st.pushed = pushed
	stuck, moved, m, err := s.quiet(st.Number, pushed, s.config().Lease)
	if err != nil {
		return err
	}
	st.Since, st.Stuck = moved, stuck
	if m != nil {
		st.Takeovers = m.takeovers
	}
	return nil
}

func (s Status) since() string {
	if s.Since.IsZero() {
		return "GitHub keeps no record of a push to " + Branch(s.Number)
	}
	return "nothing was pushed to " + Branch(s.Number) + " since " + s.Since.UTC().Format(time.RFC3339)
}

// ForPerson creates an issue for a person, through the same code as se issue
// new: labelled se and se-person and assigned to the repository's owner, so
// GitHub notifies them and no box is offered it, a sub-issue of parent where
// that is above zero, and blocked by each of blockedBy. These are the only
// issues that wait on a person.
func (s Source) ForPerson(title, body string, parent int, blockedBy []int) (Issue, error) {
	made, _, err := s.create(title, body, parent, blockedBy, []string{Label, PersonLabel})
	if err != nil {
		return Issue{}, err
	}
	owner, _, _ := strings.Cut(s.Repo, "/")
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/assignees", s.Repo, made.Number), github.F("assignees[]", owner)); err != nil {
		return made, fmt.Errorf("created #%d, but assigning it to @%s: %w", made.Number, owner, err)
	}
	return made, nil
}

// finalize labels issue n se-final: it is never superseded again, its box
// lands a PR.
func (s Source) finalize(n int) error {
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/labels", s.Repo, n), github.F("labels[]", FinalLabel)); err != nil {
		return fmt.Errorf("labelling #%d %s: %w", n, FinalLabel, err)
	}
	return nil
}

// takeOverStuck continues a stuck leaf: it records the takeover on the issue
// and labels it se-final, then fetches the leaf's branch as it stands and, where checkout is set,
// checks it out in dir. Of two boxes taking over one issue, the first comment
// wins; the other answers false and changes nothing in dir.
func (s Source) takeOverStuck(dir string, st Status, checkout bool) (took bool, err error) {
	body := fmt.Sprintf("<!-- se:takeover %d -->\nTaken over: %s, longer than the %s lease. A new box continues the branch and its PR.",
		st.Takeover.Count, st.since(), s.config().Lease) + s.boxLine()
	if won, err := s.markTakeover(st.Number, st.Takeover.Count, body); err != nil || !won {
		return false, err
	}
	if err := s.finalize(st.Number); err != nil {
		return true, err
	}
	if !checkout {
		branch := Branch(st.Number)
		_, err := s.git(dir, "fetch", "-q", "origin", "+refs/heads/"+branch+":refs/remotes/origin/"+branch)
		return true, err
	}
	if err := s.pickUp(dir, st.Number); err != nil {
		return true, fmt.Errorf("took over %s, but: %w", Branch(st.Number), err)
	}
	return true, nil
}

// markTakeover writes takeover round on issue n, its comment body carrying
// the round's marker. Where two boxes write the same round at once, the first
// comment wins and the other box withdraws its own.
func (s Source) markTakeover(n, round int, body string) (won bool, err error) {
	path := fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n)
	out, err := s.GitHub.Send("POST", path, github.F("body", body))
	if err != nil {
		return false, fmt.Errorf("recording the takeover of #%d: %w", n, err)
	}
	var mine comment
	if err := json.Unmarshal(out, &mine); err != nil || mine.ID == 0 {
		return false, fmt.Errorf("the takeover comment on #%d came back without an id: %v", n, err)
	}
	m, err := s.marks(n)
	if err != nil {
		return false, err
	}
	if m.winners[round] == mine.ID {
		return true, nil
	}
	if _, err := s.GitHub.Send("DELETE", fmt.Sprintf("repos/%s/issues/comments/%d", s.Repo, mine.ID)); err != nil {
		return false, fmt.Errorf("withdrawing a second takeover of #%d: %w", n, err)
	}
	return false, nil
}

// Waiting is an issue that waits on a person.
type Waiting struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	URL    string `json:"url"`
	Reason string `json:"reason"`
	// Blocks counts the open fleet issues it holds: those blocked by it, its
	// tree's, and so on through theirs.
	Blocks int `json:"blocks"`
}

// Waiting lists every open fleet issue labelled se-person, lowest number
// first, each with how many open issues it blocks, directly or through a tree.
func (s Source) Waiting() ([]Waiting, error) {
	all, t, err := s.survey()
	if err != nil {
		return nil, err
	}
	return waiting(all, t), nil
}

// waiting is Waiting on a survey already read.
func waiting(all []Status, t tree) []Waiting {
	// held links each open issue to the open issues it holds: its dependents,
	// and the rest of its tree, which is never offered while it waits.
	held := map[int][]int{}
	for _, n := range t.numbers() {
		for _, b := range t.openBlockers(n) {
			held[b] = append(held[b], n)
		}
		if p, ok := t.above[n]; ok {
			held[n] = append(held[n], p)
			held[p] = append(held[p], n)
		}
	}
	out := []Waiting{}
	for _, st := range all {
		if !st.Person {
			continue
		}
		seen := map[int]bool{st.Number: true}
		for queue := held[st.Number]; len(queue) > 0; queue = queue[1:] {
			if !seen[queue[0]] {
				seen[queue[0]] = true
				queue = append(queue, held[queue[0]]...)
			}
		}
		reason := st.Reason
		if reason == "" {
			reason = "labelled " + PersonLabel + " by hand; no reason recorded"
		}
		out = append(out, Waiting{st.Number, st.Title, st.URL, reason, len(seen) - 1})
	}
	return out
}
