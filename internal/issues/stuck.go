package issues

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Lease is how long a claimed issue may go without a push to its branch before
// it is stuck. It is under the routine's 4-hour schedule, so a scheduled box
// always finds a stuck issue.
const Lease = 3 * time.Hour

// PersonLabel marks an issue that waits on a person; no box is offered it.
const PersonLabel = "se-person"

// The marks se leaves in the comments it writes, so what it did survives the
// box that did it: <!-- se:takeover 1 -->, <!-- se:person -->, <!-- se:resume -->.
var mark = regexp.MustCompile(`<!-- se:(takeover|person|resume)(?: (\d+))? -->`)

// comment is the part of GitHub's issue comment object the rules read.
type comment struct {
	ID      int64     `json:"id"`
	Body    string    `json:"body"`
	Created time.Time `json:"created_at"`
}

// marks is what an issue's comments say about it since a person last resumed it.
type marks struct {
	// takeovers is the highest takeover round; two boxes racing for one round
	// count once.
	takeovers    int
	lastTakeover time.Time
	// reason is the text of the last person mark.
	reason string
	// winners maps each takeover round to its first comment's id.
	winners map[int]int64
}

func (s Source) marks(n int) (marks, error) {
	all, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return marks{}, err
	}
	m := marks{winners: map[int]int64{}}
	for _, c := range all {
		got := mark.FindStringSubmatch(c.Body)
		if got == nil {
			continue
		}
		switch got[1] {
		case "resume":
			m = marks{winners: map[int]int64{}}
		case "person":
			m.reason = strings.TrimSpace(mark.ReplaceAllString(c.Body, ""))
		case "takeover":
			round, _ := strconv.Atoi(got[2])
			m.takeovers = max(m.takeovers, round)
			if c.Created.After(m.lastTakeover) {
				m.lastTakeover = c.Created
			}
			if id, ok := m.winners[round]; !ok || c.ID < id {
				m.winners[round] = c.ID
			}
		}
	}
	return m, nil
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

// Sweep surveys the open fleet issues and gives each issue stuck a second time
// to a person: it is labelled se-person, assigned to the repository's owner
// and told why. It answers the survey as it stands afterwards and the issues
// it flagged.
func (s Source) Sweep() (all []Status, flagged []Status, err error) {
	all, err = s.Survey()
	if err != nil {
		return nil, nil, err
	}
	owner, _, _ := strings.Cut(s.Repo, "/")
	for k, st := range all {
		if !st.Stuck || st.Takeovers == 0 || st.Person {
			continue
		}
		reason := fmt.Sprintf("Stuck a second time: it was taken over %s, and nothing was pushed to %s since %s, longer than the %s lease. "+
			"A person decides how it goes on; `se issue resume %d` puts it back in the queue.",
			times(st.Takeovers), Branch(st.Number), st.Since.UTC().Format(time.RFC3339), Lease, st.Number)
		base := fmt.Sprintf("repos/%s/issues/%d", s.Repo, st.Number)
		for _, args := range [][]string{
			{"api", "-X", "POST", "-f", "labels[]=" + PersonLabel, base + "/labels"},
			{"api", "-X", "POST", "-f", "assignees[]=" + owner, base + "/assignees"},
			{"api", "-X", "POST", "-f", "body=<!-- se:person -->\n" + reason, base + "/comments"},
		} {
			if _, err := s.GH(args...); err != nil {
				return nil, flagged, fmt.Errorf("giving #%d to a person: %w", st.Number, err)
			}
		}
		st.Person, st.Stuck, st.Reason, st.Why = true, false, reason, "waits on a person"
		all[k] = st
		flagged = append(flagged, st)
	}
	return all, flagged, nil
}

func times(n int) string {
	if n == 1 {
		return "once"
	}
	return fmt.Sprintf("%d times", n)
}

// TakeOver continues a stuck issue in the git checkout dir: it records the
// takeover on the issue, then checks out the issue's branch as it stands. Of
// two boxes taking over one issue, the first comment wins; the other answers
// false and changes nothing in dir.
func (s Source) TakeOver(dir string, st Status) (took bool, err error) {
	round := st.Takeovers + 1
	body := fmt.Sprintf("<!-- se:takeover %d -->\nTaken over: nothing was pushed to %s since %s, longer than the %s lease. A new box continues the branch and its PR.",
		round, Branch(st.Number), st.Since.UTC().Format(time.RFC3339), Lease)
	out, err := s.GH("api", "-X", "POST", "-f", "body="+body, fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, st.Number))
	if err != nil {
		return false, err
	}
	var mine comment
	if err := json.Unmarshal(out, &mine); err != nil || mine.ID == 0 {
		return false, fmt.Errorf("the takeover comment on #%d came back without an id: %v", st.Number, err)
	}
	m, err := s.marks(st.Number)
	if err != nil {
		return false, err
	}
	if m.winners[round] != mine.ID {
		return false, nil
	}
	branch := Branch(st.Number)
	if _, err := git(dir, "fetch", "-q", "origin", "+refs/heads/"+branch+":refs/remotes/origin/"+branch); err != nil {
		return true, err
	}
	if _, err := git(dir, "checkout", "-q", "-B", branch, "--track", "origin/"+branch); err != nil {
		return true, fmt.Errorf("took over %s, but could not check it out: %w", branch, err)
	}
	return true, nil
}

// Waiting is an issue that waits on a person.
type Waiting struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	URL    string `json:"url"`
	Reason string `json:"reason"`
	// Blocks counts the open fleet issues it blocks, directly or through others.
	Blocks int `json:"blocks"`
}

// Waiting lists every open fleet issue labelled se-person, lowest number first.
func (s Source) Waiting() ([]Waiting, error) {
	all, err := s.Survey()
	if err != nil {
		return nil, err
	}
	dependents := map[int][]int{}
	for _, st := range all {
		for _, b := range st.blockers {
			dependents[b] = append(dependents[b], st.Number)
		}
	}
	out := []Waiting{}
	for _, st := range all {
		if !st.Person {
			continue
		}
		seen := map[int]bool{st.Number: true}
		for queue := dependents[st.Number]; len(queue) > 0; queue = queue[1:] {
			if !seen[queue[0]] {
				seen[queue[0]] = true
				queue = append(queue, dependents[queue[0]]...)
			}
		}
		reason := st.Reason
		if reason == "" {
			reason = "labelled " + PersonLabel + " by hand; no reason recorded"
		}
		out = append(out, Waiting{st.Number, st.Title, st.URL, reason, len(seen) - 1})
	}
	return out, nil
}

// Resume gives issue n back to the boxes: it removes the se-person label and
// records a resume, which resets its takeover count. A claim that is still
// stale is taken over by the next box.
func (s Source) Resume(n int) (Issue, error) {
	base := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	got, err := api[issue](s, base, false)
	if err != nil {
		return Issue{}, err
	}
	i := got[0]
	waits := false
	for _, l := range i.Labels {
		waits = waits || l.Name == PersonLabel
	}
	if i.PullRequest != nil || i.State != "open" || !waits {
		return Issue{}, fmt.Errorf("#%d is not an open issue waiting on a person (labelled %s)", n, PersonLabel)
	}
	// The resume is recorded before the label goes, so an issue back in the
	// queue never keeps its old takeover count.
	body := "<!-- se:resume -->\nResumed by a person: back in the queue, its takeover count reset."
	if _, err := s.GH("api", "-X", "POST", "-f", "body="+body, base+"/comments"); err != nil {
		return Issue{}, err
	}
	if _, err := s.GH("api", "-X", "DELETE", base+"/labels/"+PersonLabel); err != nil {
		return Issue{}, err
	}
	return Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL}, nil
}
