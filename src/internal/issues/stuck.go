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
// box that did it: <!-- se:takeover 1 -->, <!-- se:person -->, <!-- se:resume -->,
// and <!-- se:takeover-head abc -->, the PR head a conflict takeover found.
var mark = regexp.MustCompile(`<!-- se:(takeover|person|resume|takeover-head)(?: ([0-9a-f]+))? -->`)

// comment is the part of GitHub's issue comment object the rules read.
type comment struct {
	ID      int64     `json:"id"`
	Body    string    `json:"body"`
	Created time.Time `json:"created_at"`
	// IssueURL is the API URL of the issue it is on.
	IssueURL string `json:"issue_url"`
}

// marks is what an issue's comments say about it since a person last resumed it.
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

// lease reads whether a claimed leaf is stuck: nothing pushed to its branch,
// nor a takeover recorded, for longer than the lease. Its comments are read
// only where the last push is that old.
func (s Source) lease(st *Status) error {
	pushed, err := s.lastPush(st.Number)
	if err != nil {
		return err
	}
	st.Since, st.pushed = pushed, pushed
	if s.now().Sub(st.Since) <= s.config().Lease {
		return nil
	}
	m, err := s.marks(st.Number)
	if err != nil {
		return err
	}
	st.Takeovers = m.takeovers
	if m.lastTakeover.After(st.Since) {
		st.Since = m.lastTakeover
	}
	st.Stuck = s.now().Sub(st.Since) > s.config().Lease
	return nil
}

func (s Status) since() string {
	if s.Since.IsZero() {
		return "GitHub keeps no record of a push to " + Branch(s.Number)
	}
	return "nothing was pushed to " + Branch(s.Number) + " since " + s.Since.UTC().Format(time.RFC3339)
}

// toPerson gives a final issue that is stuck to a person: an issue for a
// person holds it, and it waits on that one.
func (s Source) toPerson(st *Status) error {
	reason := fmt.Sprintf("Stuck on its final attempt (labelled %s): %s, longer than the %s lease.", FinalLabel, st.since(), s.config().Lease)
	held, err := s.hold(st.Issue, reason)
	if err != nil {
		return err
	}
	st.Stuck, st.Takeover, st.claimed = false, nil, false
	st.Why = fmt.Sprintf("blocked by #%d", held.Number)
	return nil
}

// holdTitle is the title of the issue for a person that hold mints, and
// holdOf reads the issue it holds back from it.
const holdTitle = "Decide how #%d goes on: %s"

var holdOf = regexp.MustCompile(`^Decide how #(\d+) goes on: `)

// hold takes issue i out of the queue until a person has looked: it mints an
// issue for the person that says why, links i as blocked by it (GitHub's
// native link), and records on i that it waits on that one, with a resume
// that clears its takeovers. i itself never waits on a person, and is no
// longer final: once the person closes their issue, i is back in the queue
// with a fresh attempt. This is the one link se writes on an issue that
// already exists: no box is left to write it.
func (s Source) hold(i Issue, reason string) (Issue, error) {
	title := fmt.Sprintf(holdTitle, i.Number, i.Title)
	body := fmt.Sprintf("%s\n\n#%d (%s) is blocked by this issue. Decide how it goes on, say so here, and close this issue: #%d is then back in the queue with a fresh attempt.", reason, i.Number, i.URL, i.Number)
	made, err := s.ForPerson(title, body, 0, nil)
	if err != nil {
		return Issue{}, fmt.Errorf("giving #%d to a person: %w", i.Number, err)
	}
	if err := s.Blocking(made, []int{i.Number}); err != nil {
		return made, err
	}
	base := fmt.Sprintf("repos/%s/issues/%d", s.Repo, i.Number)
	note := fmt.Sprintf("<!-- se:person -->\n%s\n\nIt is blocked by #%d, an issue for a person; closing #%d gives it back to the boxes, no longer final.\n<!-- se:resume -->", reason, made.Number, made.Number)
	if _, err := s.GitHub.Send("POST", base+"/comments", github.F("body", note)); err != nil {
		return made, fmt.Errorf("created #%d for a person, but recording it on #%d: %w", made.Number, i.Number, err)
	}
	// A 404 is a label already gone.
	if _, err := s.GitHub.Send("DELETE", base+"/labels/"+FinalLabel); err != nil && github.Status(err) != 404 {
		return made, fmt.Errorf("created #%d for a person, but taking %s off #%d: %w", made.Number, FinalLabel, i.Number, err)
	}
	if s.Flagged != nil {
		s.Flagged(i, reason)
	}
	return made, nil
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

// finalize labels issue n se-final: its next failure goes to a person.
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

// Resume gives issue n back to the boxes: it removes the se-person label and
// the se-final one, and records a resume, which resets its takeover count, so
// it gets one more attempt. A claim that is still stale is taken over by the
// next box.
func (s Source) Resume(n int) (Issue, error) {
	base := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	got, err := api[issue](s, base, false)
	if err != nil {
		return Issue{}, err
	}
	i := got[0]
	if i.PullRequest != nil || i.State != "open" || !i.labelled(PersonLabel) {
		return Issue{}, fmt.Errorf("#%d is not an open issue waiting on a person (labelled %s)", n, PersonLabel)
	}
	// The resume is recorded before the label goes, so an issue back in the
	// queue never keeps its old takeover count.
	body := "<!-- se:resume -->\nResumed by a person: back in the queue, its takeover count reset, no longer final."
	if _, err := s.GitHub.Send("POST", base+"/comments", github.F("body", body)); err != nil {
		return Issue{}, err
	}
	for _, l := range []string{FinalLabel, PersonLabel} {
		if !i.labelled(l) {
			continue
		}
		if _, err := s.GitHub.Send("DELETE", base+"/labels/"+l); err != nil {
			return Issue{}, err
		}
	}
	return Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL}, nil
}
