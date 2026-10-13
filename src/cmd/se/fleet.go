package main

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/mb-89/SE/src/internal/issues"
)

func init() {
	register(Command{
		Name:    "fleet check",
		Usage:   "fleet check [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "list what is broken in the fleet, each with its remedy",
		Details: "read GitHub and list every finding: a stalled root, a conflicted, red or green but unmerged PR, a claim with no PR, a leftover claim, an impossible block, an issue waiting on a person. Each names its issue, its PR and its remedy, in the order the coordination skill fixes them. Nothing found, it says healthy. spec/coordination.md has the rules.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "fleet check")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			found, err := s.Check()
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Healthy  bool             `json:"healthy"`
					Findings []issues.Finding `json:"findings"`
				}{len(found) == 0, append([]issues.Finding{}, found...)})
				return Reply{Text: string(data)}, err
			}
			if len(found) == 0 {
				return Reply{Text: "healthy"}, nil
			}
			lines := make([]string, len(found))
			for k, f := range found {
				lines[k] = findingText(f)
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
	register(Command{
		Name:    "fleet fix",
		Usage:   "fleet fix [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "fix what fleet check finds that needs no checkout",
		Details: "run fleet check and apply, in its order, every remedy that needs no checkout: auto-merge goes on, and a finding with no other remedy becomes an se issue, or an se-person one where it is a judgment. Each fix is recorded on the finding's issue, and a finding back after its fix goes to a person. A takeover is named for the box to run. A ready issue it made fires the routine once.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "fleet fix")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			found, err := s.Check()
			if err != nil {
				return Reply{}, err
			}
			done, err := s.Fix(found)
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			for _, d := range done {
				if d.Ready {
					fanout = fire()
					break
				}
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Healthy bool           `json:"healthy"`
					Fixed   []issues.Fixed `json:"fixed"`
					Fanout  string         `json:"fanout,omitempty"`
				}{len(found) == 0, append([]issues.Fixed{}, done...), fanout})
				return Reply{Text: string(data)}, err
			}
			if len(done) == 0 {
				return Reply{Text: "healthy"}, nil
			}
			lines := make([]string, 0, len(done)+1)
			for _, d := range done {
				lines = append(lines, fmt.Sprintf("%s #%d: %s\n  did: %s", d.Kind, d.Issue, d.What, d.Did))
			}
			if fanout != "" {
				lines = append(lines, fanout)
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
}

// findingText is one finding: its kind and issue, what is wrong, and its remedy.
func findingText(f issues.Finding) string {
	head := fmt.Sprintf("%s #%d", f.Kind, f.Issue)
	if f.PR > 0 {
		head += fmt.Sprintf(" (PR #%d)", f.PR)
	}
	return fmt.Sprintf("%s: %s\n  remedy: %s", head, f.What, f.Remedy)
}
