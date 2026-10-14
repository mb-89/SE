package issues

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"github.com/mb-89/SE/src/modules/io/github"
)

// seLine finds a line of a body that carries an se block, and names its
// kind: <!-- se:retro unattended --> is a retro's, the skills line a skills'.
var seLine = regexp.MustCompile(`<!-- se:([a-z-]+)`)

// Edited is what Edit wrote: the issue as it stands now, and the se blocks of
// its old body it carried into the new one.
type Edited struct {
	Issue Issue `json:"issue"`
	// Kept are the old body's se lines the new body kept, in their order.
	Kept []string `json:"kept,omitempty"`
}

// Edit rewrites se issue n's title, where title is not nil, and its body,
// where body is not nil, through the same code as se issue new: an empty
// title is refused, and so is a title an open se issue under n's parent has
// already, n left out; the body ends in NewMark. A new body keeps each se
// block of the old one (a line holding <!-- se:KIND ... -->, the mark aside)
// whose kind it does not carry itself, so the skills line and a retro's or an
// overhaul's mark stay. With neither, the body is written again as it stands,
// its mark put back. A pull request, or an issue not labelled se, is refused.
func (s Source) Edit(n int, title, body *string) (Edited, error) {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		if st := github.Status(err); st == 404 || st == 410 {
			return Edited{}, fmt.Errorf("#%d does not exist in %s", n, s.Repo)
		}
		return Edited{}, err
	}
	old := got[0]
	switch {
	case old.PullRequest != nil:
		return Edited{}, fmt.Errorf("#%d is a pull request, not an issue", n)
	case !old.labelled(Label):
		return Edited{}, fmt.Errorf("#%d is not an se issue (labelled %s): se edits only its own", n, Label)
	}
	newTitle := old.Title
	if title != nil {
		if err := titled(*title); err != nil {
			return Edited{}, err
		}
		newTitle = *title
		if strings.TrimSpace(newTitle) != strings.TrimSpace(old.Title) {
			parent, err := s.parentOf(n)
			if err != nil {
				return Edited{}, err
			}
			if dup, err := s.duplicate(newTitle, parent, n); err != nil {
				return Edited{}, err
			} else if dup > 0 {
				return Edited{}, fmt.Errorf("#%d is an open se issue titled %q under the same parent already", dup, strings.TrimSpace(newTitle))
			}
		}
	}
	text, kept := old.Body, []string(nil)
	if body != nil {
		text, kept = carry(old.Body, *body)
	}
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	out, err := s.GitHub.Send("PATCH", path, github.F("title", newTitle), github.F("body", marked(text)))
	if err != nil {
		return Edited{}, err
	}
	var i issue
	if err := json.Unmarshal(out, &i); err != nil || i.Number == 0 {
		return Edited{}, fmt.Errorf("gh api %s answered no issue: %v", path, err)
	}
	return Edited{Issue: Issue{Number: i.Number, Title: i.Title, Body: i.Body, URL: i.URL, id: i.ID}, Kept: kept}, nil
}

// carry answers body with each se line of old whose kind body does not carry
// itself appended, the mark aside (marked writes it), and those lines.
func carry(old, body string) (string, []string) {
	has := map[string]bool{}
	for _, m := range seLine.FindAllStringSubmatch(body, -1) {
		has[m[1]] = true
	}
	var kept []string
	for _, line := range strings.Split(old, "\n") {
		line = strings.TrimSpace(line)
		m := seLine.FindStringSubmatch(line)
		if m == nil || m[1] == "new" || has[m[1]] {
			continue
		}
		kept = append(kept, line)
	}
	text := strings.TrimRight(strings.ReplaceAll(body, NewMark, ""), " \n")
	for _, line := range kept {
		text += "\n\n" + line
	}
	return text, kept
}
