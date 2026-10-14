// Package stuck is the module issues/stuck: stuck work. It holds the lease on
// a claimed leaf, the marks its takeovers and its holds leave on an issue,
// the rule for when a claim has stopped moving, and se issue resume, which
// gives an issue waiting on a person back to the boxes. It is a compute
// module: it reaches GitHub and git only through its request ports.
package stuck

import (
	"regexp"
	"strconv"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/lib/rest"
)

// Lease is the built-in value of issues/stuck/config/lease: how long a
// claimed leaf may go without a push to its branch before it is stuck. It is
// under the routine's 4-hour schedule, so a scheduled box always finds a
// stuck issue.
const Lease = 3 * time.Hour

// PersonLabel marks an issue that waits on a person, the repository's owner,
// who is assigned to it; no box is offered it, or a tree containing it.
const PersonLabel = "se-person"

// FinalLabel marks an issue on its last attempt: its next failure goes to a
// person.
const FinalLabel = "se-final"

// The module's request ports, which the wiring binds to io/github's get and
// send and io/git's origin.
var (
	get    = index.Ask[rest.Get, []byte]("get", "Reads an issue from GitHub.")
	send   = index.Ask[rest.Send, []byte]("send", "Writes to an issue on GitHub: a comment, or a label taken off.")
	origin = index.Ask[string, string]("origin", "Answers OWNER/NAME, the repository the workspace's origin names.")
)

// Module declares stuck work on the index: the lease and se issue resume.
var Module = index.Declare("issues/stuck", "Stuck work: the lease on a claimed leaf, its takeovers, and the issue for a person that holds a claim stuck on its final attempt.",
	index.Config("lease", Lease, "How long a claimed leaf may go without a push to its branch before it is stuck; it is under the routine's 4-hour schedule."),
	get, send, origin,
	resumeCommand,
)

func init() { index.Register(Module) }

// The marks se leaves in the comments it writes, so what it did survives the
// box that did it: <!-- se:takeover 1 -->, <!-- se:person -->, <!-- se:resume -->,
// and <!-- se:takeover-head abc -->, the PR head a conflict takeover found.
var mark = regexp.MustCompile(`<!-- se:(takeover|person|resume|takeover-head)(?: ([0-9a-f]+))? -->`)

// Comment is the part of a comment on an issue the marks are read from.
type Comment struct {
	ID      int64
	Body    string
	Created time.Time
}

// Marks is what an issue's comments say about its stuck work since a person
// last resumed it.
type Marks struct {
	// Takeovers is the highest takeover round; two boxes racing for one round
	// count once. Head is the PR head that round's conflict takeover found,
	// so a box tells a takeover still in flight from a second conflict.
	Takeovers    int
	Head         string
	LastTakeover time.Time
	// Person is the body of the comment that carries the last person mark,
	// as GitHub holds it.
	Person string
	// Winners maps each takeover round to its first comment's id.
	Winners map[int]int64
}

// Read folds one more comment, the next oldest, into m, and says whether it
// resumed the issue: a resume mark clears every mark before it.
func (m *Marks) Read(c Comment) (resumed bool) {
	if m.Winners == nil {
		m.Winners = map[int]int64{}
	}
	round := 0
	for _, got := range mark.FindAllStringSubmatch(c.Body, -1) {
		switch got[1] {
		case "resume":
			*m, resumed = Marks{Winners: map[int]int64{}}, true
		case "person":
			m.Person = c.Body
		case "takeover":
			round, _ = strconv.Atoi(got[2])
			if round > m.Takeovers {
				m.Takeovers, m.Head = round, ""
			}
			if c.Created.After(m.LastTakeover) {
				m.LastTakeover = c.Created
			}
			if id, ok := m.Winners[round]; !ok || c.ID < id {
				m.Winners[round] = c.ID
			}
		case "takeover-head":
			if round == m.Takeovers {
				m.Head = got[2]
			}
		}
	}
	return resumed
}

// PersonMarked says whether a comment's body carries a person mark: the
// issue went to a person.
func PersonMarked(body string) bool {
	for _, got := range mark.FindAllStringSubmatch(body, -1) {
		if got[1] == "person" {
			return true
		}
	}
	return false
}

// Quiet is the one rule for when a claim has stopped moving, which the lease
// (stuck, with the lease as window) and se fleet check both read: nothing
// pushed to its branch since pushed, nor a takeover of it recorded since
// lastTakeover, for longer than window by now. moved is when the claim last
// moved, its push or its last takeover.
func Quiet(now, pushed, lastTakeover time.Time, window time.Duration) (quiet bool, moved time.Time) {
	moved = pushed
	if lastTakeover.After(moved) {
		moved = lastTakeover
	}
	return now.Sub(moved) > window, moved
}
