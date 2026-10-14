package issues

import (
	"fmt"
	"strings"

	"github.com/mb-89/SE/src/internal/io/github"
)

// Superseded is what Supersede did: the issue it closed and the successor
// that carries its work on.
type Superseded struct {
	// Issue is the superseded issue, now closed.
	Issue int `json:"issue"`
	// Successor is the final issue made in its place.
	Successor Issue `json:"successor"`
	// Parent is the parent the successor shares with it; zero for none.
	Parent int `json:"parent,omitempty"`
	// BlockedBy are its open blockers, which block the successor too.
	BlockedBy []int `json:"blocked_by"`
	// Blocks are its open dependents, now blocked by the successor.
	Blocks []int `json:"blocks,omitempty"`
	// Ready is true where nothing open blocks the successor.
	Ready bool `json:"ready"`
}

// Supersede is the second of the two ways a box closes the issue it took (the
// first is a PR): issue n's successor, made through the same code as se issue
// new, carries n's title and text and the open questions the box could not
// answer, labelled se-final. It has n's parent and n's open blockers, and n's
// open dependents are linked as blocked by it. Then n closes, its comment
// naming the successor. A final issue is refused: its box lands a PR.
func (s Source) Supersede(n int, questions string) (Superseded, error) {
	if strings.TrimSpace(questions) == "" {
		return Superseded{}, fmt.Errorf("superseding #%d needs the open questions its box could not answer", n)
	}
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		if st := github.Status(err); st == 404 || st == 410 {
			return Superseded{}, fmt.Errorf("#%d does not exist in %s", n, s.Repo)
		}
		return Superseded{}, err
	}
	old := got[0]
	switch {
	case old.PullRequest != nil:
		return Superseded{}, fmt.Errorf("#%d is a pull request, not an issue", n)
	case old.State != "open":
		return Superseded{}, fmt.Errorf("#%d is closed already: only an open issue is superseded", n)
	case old.labelled(FinalLabel):
		return Superseded{}, fmt.Errorf("#%d is final (%s): it is never superseded again, its box lands a PR", n, FinalLabel)
	}
	parent, err := s.parentOf(n)
	if err != nil {
		return Superseded{}, err
	}
	blockers, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/dependencies/blocked_by?per_page=100", s.Repo, n), true)
	if err != nil {
		return Superseded{}, err
	}
	sup := Superseded{Issue: n, Parent: parent, BlockedBy: []int{}}
	for _, b := range blockers {
		if b.State == "open" {
			sup.BlockedBy = append(sup.BlockedBy, b.Number)
		}
	}
	if sup.Blocks, err = s.Dependents(n); err != nil {
		return Superseded{}, err
	}
	text := strings.TrimSpace(strings.ReplaceAll(old.Body, NewMark, ""))
	body := fmt.Sprintf("Supersedes #%d, whose box could not close it with a PR. This is its last attempt (%s): its box lands a PR.\n\n%s\n\n## Open questions\n%s",
		n, FinalLabel, text, strings.TrimSpace(questions))
	made, ready, err := s.Create(old.Title, body, parent, sup.BlockedBy, FinalLabel)
	if err != nil {
		return Superseded{}, err
	}
	sup.Successor, sup.Ready = made, ready
	if err := s.Blocking(made, sup.Blocks); err != nil {
		return sup, err
	}
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	comment := fmt.Sprintf("Superseded by #%d, which carries this issue on with the questions its box could not answer.\n%s", made.Number, made.URL)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", comment)); err != nil {
		return sup, fmt.Errorf("created #%d (%s), but commenting on #%d: %w", made.Number, made.URL, n, err)
	}
	if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", "not_planned")); err != nil {
		return sup, fmt.Errorf("created #%d (%s), but closing #%d: %w", made.Number, made.URL, n, err)
	}
	return sup, nil
}

// parentOf names the issue n is a sub-issue of, or zero where it is none.
func (s Source) parentOf(n int) (int, error) {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/parent", s.Repo, n), false)
	if err != nil {
		if github.Status(err) == 404 {
			return 0, nil
		}
		return 0, err
	}
	return got[0].Number, nil
}
