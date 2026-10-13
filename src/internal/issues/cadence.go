package issues

import "fmt"

// RetroCadence is how many se issues close between two retros: at this many
// closed since the last retro closed, se issue next --take starts an
// unattended one and takes it before all other work (spec/retro.md).
const RetroCadence = 10

// Cadence is where the retro cadence stands.
type Cadence struct {
	// Closed counts the se issues closed since the last retro closed, retros
	// not counted; with no retro closed yet, the whole history.
	Closed int `json:"closed"`
	// Previous is the last closed retro; 0 where none has closed.
	Previous int `json:"previous,omitempty"`
	// Open is an open retro, attended or not; 0 where none is open. While one
	// is open no second one is started.
	Open int `json:"open,omitempty"`
}

// Due says a retro is to be started: the cadence is reached and none is open.
func (c Cadence) Due() bool { return c.Closed >= RetroCadence && c.Open == 0 }

// Line says where the cadence stands, in one sentence.
func (c Cadence) Line() string {
	since := "and no retro has closed yet"
	if c.Previous != 0 {
		since = fmt.Sprintf("since the retro #%d closed", c.Previous)
	}
	issues := "se issues"
	if c.Closed == 1 {
		issues = "se issue"
	}
	head := fmt.Sprintf("%d %s closed %s", c.Closed, issues, since)
	switch {
	case c.Open != 0:
		return fmt.Sprintf("%s; the retro #%d is open.", head, c.Open)
	case c.Due():
		return fmt.Sprintf("A retro is due: %s (the cadence is %d); se issue next --take starts it unattended.", head, RetroCadence)
	default:
		return fmt.Sprintf("%s; a retro is due at %d.", head, RetroCadence)
	}
}

// Cadence reads where the retro cadence stands from GitHub.
func (s Source) Cadence() (Cadence, error) {
	var c Cadence
	last, ok, _, err := s.lastRetro(0)
	if err != nil {
		return Cadence{}, err
	}
	var w RetroWindow
	if ok {
		c.Previous, w.Since = last.Number, last.ClosedAt.UTC()
	}
	open, err := api[issue](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=open&per_page=100", s.Repo, RetroLabel), true)
	if err != nil {
		return Cadence{}, err
	}
	for _, r := range open {
		if r.PullRequest == nil && (c.Open == 0 || r.Number < c.Open) {
			c.Open = r.Number
		}
	}
	closed, err := api[past](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=closed&per_page=100%s", s.Repo, Label, w.since()), true)
	if err != nil {
		return Cadence{}, err
	}
	// GitHub's since is about updates; the window is about closing.
	for _, i := range closed {
		if i.PullRequest == nil && !i.labelled(RetroLabel) && i.ClosedAt.After(w.Since) {
			c.Closed++
		}
	}
	return c, nil
}

// TakeRetro starts the retro the cadence has made due and claims it in the
// git checkout dir, ahead of all other work: ok is false, with nothing
// created, where none is due. The retro runs unattended, as nobody started it.
func (s Source) TakeRetro(dir string) (took Issue, ok bool, c Cadence, err error) {
	if c, err = s.Cadence(); err != nil || !c.Due() {
		return Issue{}, false, c, err
	}
	r, err := s.NewRetro("", true)
	if err != nil {
		return Issue{}, false, c, err
	}
	c.Open = r.Number
	claimed, err := Claim(dir, r.Number)
	if err != nil || !claimed {
		return Issue{}, false, c, err
	}
	took = r.Issue
	took.Retro = true
	return took, true, c, nil
}
