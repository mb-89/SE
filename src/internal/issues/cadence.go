package issues

import (
	"fmt"

	"github.com/mb-89/SE/src/internal/io/github"
)

// RetroCadence is how many se issues close between two retros: at this many
// closed since the last retro closed, se issue pull --take starts an
// unattended one and takes it before all other work (spec/retro.md).
const RetroCadence = 10

// OverhaulCadence is how many retros close between two overhauls: at this
// many closed since the last overhaul closed, se issue pull --take starts an
// unattended one and takes it first (spec/overhaul.md).
const OverhaulCadence = 5

// cadenceRule is one cadence: a run (a retro, an overhaul) started every so
// many closed issues of a kind.
type cadenceRule struct {
	// Kind names the run, article the word before it.
	kind, article string
	// label marks the run's issues; counts labels the closed issues counted,
	// noun names one of them, and skip the labels left out of the count.
	label, counts, noun string
	skip                []string
	every               int
}

var (
	retroRule    = cadenceRule{"retro", "a", RetroLabel, Label, "se issue", []string{RetroLabel, OverhaulLabel}, RetroCadence}
	overhaulRule = cadenceRule{"overhaul", "an", OverhaulLabel, RetroLabel, "retro", nil, OverhaulCadence}
)

// Cadence is where one cadence stands.
type Cadence struct {
	// Kind is the run the cadence starts: retro or overhaul.
	Kind string `json:"kind"`
	// Every is the cadence: at this many closed, a run is due.
	Every int `json:"every"`
	// Closed counts the issues closed since the last run closed (se issues,
	// retros and overhauls not counted, for a retro; retros, for an
	// overhaul); with no run closed yet, the whole history.
	Closed int `json:"closed"`
	// Previous is the last closed run; 0 where none has closed.
	Previous int `json:"previous,omitempty"`
	// Open is an open run, attended or not; 0 where none is open. While one
	// is open no second one is started.
	Open int `json:"open,omitempty"`
}

func (c Cadence) rule() cadenceRule {
	if c.Kind == overhaulRule.kind {
		return overhaulRule
	}
	return retroRule
}

// Due says a run is to be started: the cadence is reached and none is open.
func (c Cadence) Due() bool { return c.Every > 0 && c.Closed >= c.Every && c.Open == 0 }

// Line says where the cadence stands, in one sentence.
func (c Cadence) Line() string {
	r := c.rule()
	since := fmt.Sprintf("and no %s has closed yet", r.kind)
	if c.Previous != 0 {
		since = fmt.Sprintf("since the %s #%d closed", r.kind, c.Previous)
	}
	noun := r.noun + "s"
	if c.Closed == 1 {
		noun = r.noun
	}
	head := fmt.Sprintf("%d %s closed %s", c.Closed, noun, since)
	switch {
	case c.Open != 0:
		return fmt.Sprintf("%s; the %s #%d is open.", head, r.kind, c.Open)
	case c.Due():
		article := string(r.article[0]-'a'+'A') + r.article[1:]
		return fmt.Sprintf("%s %s is due: %s (the cadence is %d); se issue pull --take starts it unattended.", article, r.kind, head, c.Every)
	default:
		return fmt.Sprintf("%s; %s %s is due at %d.", head, r.article, r.kind, c.Every)
	}
}

// Cadence reads where the retro cadence stands from GitHub.
func (s Source) Cadence() (Cadence, error) { return s.cadence(retroRule) }

// OverhaulCadence reads where the overhaul cadence stands from GitHub.
func (s Source) OverhaulCadence() (Cadence, error) { return s.cadence(overhaulRule) }

func (s Source) cadence(r cadenceRule) (Cadence, error) {
	c := Cadence{Kind: r.kind, Every: r.every}
	last, ok, _, err := s.lastClosed(r.label, 0)
	if err != nil {
		return Cadence{}, err
	}
	var w RetroWindow
	if ok {
		c.Previous, w.Since = last.Number, last.ClosedAt.UTC()
	}
	if c.Open, err = s.firstOpen(r.label); err != nil {
		return Cadence{}, err
	}
	closed, err := api[past](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100%s", s.Repo, r.counts, w.since()), true)
	if err != nil {
		return Cadence{}, err
	}
	// GitHub's since is about updates; the window is about closing.
	for _, i := range closed {
		skipped := false
		for _, l := range r.skip {
			skipped = skipped || i.labelled(l)
		}
		// A retro closed as a duplicate never ran: the overhaul counts it not.
		skipped = skipped || i.labelled(RetroLabel) && !ran(i)
		if i.PullRequest == nil && !skipped && i.ClosedAt.After(w.Since) {
			c.Closed++
		}
	}
	return c, nil
}

// firstOpen is the open issue labelled label with the lowest number; 0 where
// none is open.
func (s Source) firstOpen(label string) (int, error) {
	open, err := api[issue](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=open&per_page=100", s.Repo, label), true)
	if err != nil {
		return 0, err
	}
	first := 0
	for _, o := range open {
		if o.PullRequest == nil && (first == 0 || o.Number < first) {
			first = o.Number
		}
	}
	return first, nil
}

// ran says whether a closed run (a retro, an overhaul) ran: one closed as a
// duplicate of another never did.
func ran(p past) bool { return p.StateReason != duplicate }

// duplicate is GitHub's state_reason for an issue closed as a duplicate.
const duplicate = "duplicate"

// TakeRetro starts the retro the cadence has made due and claims it in the
// git checkout dir, ahead of all other work: ok is false, with nothing
// created, where none is due, and with the one it started closed as a
// duplicate where a race started a lower one too. The retro runs unattended,
// as nobody started it.
func (s Source) TakeRetro(dir string) (took Issue, ok bool, c Cadence, err error) {
	return s.takeDue(retroRule, dir, s.startRetro)
}

func (s Source) startRetro() (Issue, error) {
	r, err := s.NewRetro("", true)
	r.Retro = true
	return r.Issue, err
}

// TakeOverhaul starts the overhaul the cadence has made due and claims it in
// the git checkout dir, ahead of all other work, a due retro included: ok is
// false, with nothing created, where none is due, and with the one it started
// closed as a duplicate where a race started a lower one too. It runs
// unattended.
func (s Source) TakeOverhaul(dir string) (took Issue, ok bool, c Cadence, err error) {
	return s.takeDue(overhaulRule, dir, s.startOverhaul)
}

func (s Source) startOverhaul() (Issue, error) {
	o, err := s.NewOverhaul(true)
	o.Overhaul = true
	return o.Issue, err
}

// TakeDue starts and claims the run a cadence has made due, ahead of all
// other work: an overhaul first, else a retro. ok is false, with nothing
// created, where neither is due.
func (s Source) TakeDue(dir string) (took Issue, ok bool, c Cadence, err error) {
	if took, ok, c, err = s.TakeOverhaul(dir); err != nil || ok {
		return took, ok, c, err
	}
	return s.TakeRetro(dir)
}

func (s Source) takeDue(r cadenceRule, dir string, start func() (Issue, error)) (took Issue, ok bool, c Cadence, err error) {
	if c, err = s.cadence(r); err != nil || !c.Due() {
		return Issue{}, false, c, err
	}
	return s.startDue(r, dir, c, start)
}

// startDue starts the run cadence c found due and claims it. Reading the
// cadence and creating the run are not one step, so two boxes may both find
// it due and both start one: after creating its run, a box reads the open
// runs again, and where one with a lower number is open it closes its own as
// a duplicate of that one, claims nothing, and goes on to other work (ok is
// false, c.Open the run that stands).
func (s Source) startDue(r cadenceRule, dir string, c Cadence, start func() (Issue, error)) (took Issue, ok bool, _ Cadence, err error) {
	made, err := start()
	if err != nil {
		return Issue{}, false, c, err
	}
	// Two boxes can both read the cadence as due and both start a run: look
	// again, and where a lower one is open, this one is the duplicate.
	again, err := s.cadence(r)
	if err != nil {
		return Issue{}, false, c, err
	}
	if again.Open != 0 && again.Open < made.Number {
		return Issue{}, false, again, s.closeDuplicate(r, made.Number, again.Open)
	}
	c.Open = made.Number
	claimed, err := s.Claim(dir, made.Number)
	if err != nil || !claimed {
		return Issue{}, false, c, err
	}
	return made, true, c, nil
}

// closeDuplicate closes run n as a duplicate of run of, saying why.
func (s Source) closeDuplicate(r cadenceRule, n, of int) error {
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	body := fmt.Sprintf("Duplicate of #%d: another box started that %s while this one did, and the lower number stands. This one closes without running.", of, r.kind)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", body)); err != nil {
		return fmt.Errorf("closing the duplicate %s #%d: %w", r.kind, n, err)
	}
	if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", duplicate)); err != nil {
		return fmt.Errorf("closing the duplicate %s #%d: %w", r.kind, n, err)
	}
	return nil
}

// Counts names what the cadence counts, in the plural.
func (c Cadence) Counts() string { return c.rule().noun + "s" }
