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
		Details: "read GitHub and list every finding: a stalled root, a conflicted, red or green but unmerged PR, a claim with no PR, a leftover claim, an impossible block, an issue waiting on a person. Each names its issue, its PR and its remedy, in the order the coordination skill fixes them. Nothing found, it says healthy. With fan-out on, a fan-out the routine refused with 429, which se issue pull --take keeps on the alive claims with its retry time, fires once that time has passed and the fleet still needs the box, and a last line says so. spec/coordination.md has the rules.",
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
			// With fan-out on, a fan-out the routine refused, kept on the
			// alive claims, fires once its retry time has passed.
			var found []issues.Finding
			fanout := ""
			if c.fanOutOn() {
				found, fanout, err = s.CheckFanOut(c.shoot)
			} else {
				found, err = s.Check()
			}
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Healthy  bool             `json:"healthy"`
					Findings []issues.Finding `json:"findings"`
					Fanout   string           `json:"fanout,omitempty"`
				}{len(found) == 0, append([]issues.Finding{}, found...), fanout})
				return Reply{Text: string(data)}, err
			}
			lines := make([]string, 0, len(found)+1)
			for _, f := range found {
				lines = append(lines, findingText(f))
			}
			if len(found) == 0 {
				lines = append(lines, "healthy")
			}
			if fanout != "" {
				lines = append(lines, fanout)
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
	register(Command{
		Name:    "fleet fix",
		Usage:   "fleet fix [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "fix what fleet check finds that needs no checkout",
		Details: "run fleet check and apply, in its order, every remedy that needs no checkout: auto-merge goes on, a leftover claim of a closed issue is left to the prune workflow for a day after the close, any other leftover claim's branch main holds whole is deleted by a git push from the workspace, and a finding with no other remedy becomes an se issue, or an se-person one where it is a judgment. Each fix is recorded on the finding's issue, and a finding back after its fix goes to a person. A remedy that fails is reported, and the ones after it are still applied. A takeover is named for the box to run. A ready issue it made fires the routine once.",
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
			done := s.Fix(c.Workspace, found)
			fanout := ""
			for _, d := range done {
				if d.Ready {
					fanout = c.fire()
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
	register(Command{
		Name:    "fleet prune",
		Usage:   "fleet prune [--apply] [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "list the stray branches; --apply deletes them",
		Details: "list every issue-<n> branch whose issue is closed and every claude/* branch whose last commit is more than an hour old, each with no open PR. --apply deletes them; without it nothing is deleted. It never touches main or any other branch. The prune workflow runs it with the repository's token.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "fleet prune")
			apply := fs.Bool("apply", false, "delete the branches it lists")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			strays, err := s.Strays()
			if err != nil {
				return Reply{}, err
			}
			var pruneErr error
			if *apply {
				strays, pruneErr = s.Prune(strays)
			}
			lines := make([]string, len(strays))
			for k, b := range strays {
				verb := "stray"
				if b.Deleted {
					verb = "deleted"
				}
				lines[k] = fmt.Sprintf("%s %s at %s: %s", verb, b.Branch, b.SHA, b.Why)
			}
			if pruneErr != nil {
				return Reply{}, fmt.Errorf("%w\n%s", pruneErr, strings.Join(lines, "\n"))
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Strays []issues.Stray `json:"strays"`
				}{append([]issues.Stray{}, strays...)})
				return Reply{Text: string(data)}, err
			}
			if len(strays) == 0 {
				return Reply{Text: "no stray branches"}, nil
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
	register(Command{
		Name:    "fleet refresh",
		Usage:   "fleet refresh [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "merge main into each auto-merge PR behind it, approve its CI",
		Details: "for every open PR against main with auto-merge on whose head main has moved past: merge main into it through GitHub's update-branch and approve the pull_request run of the ci workflow that the update starts on its new head, since main's ruleset merges a PR only when it is up to date with main, its required check waits on that run, and a run the repository's token starts through update-branch waits in action_required for approval. A PR that conflicts with main is left to its takeover. A PR whose update fails is reported, and the others are still updated. The refresh workflow runs it with the repository's token on every push to main.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "fleet refresh")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			done, refreshErr := s.Refresh()
			lines := make([]string, len(done))
			for k, r := range done {
				lines[k] = fmt.Sprintf("PR #%d (%s): %s", r.PR, r.Branch, r.Did)
			}
			if refreshErr != nil {
				return Reply{}, fmt.Errorf("%w\n%s", refreshErr, strings.Join(lines, "\n"))
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Refreshed []issues.Refreshed `json:"refreshed"`
				}{append([]issues.Refreshed{}, done...)})
				return Reply{Text: string(data)}, err
			}
			if len(done) == 0 {
				return Reply{Text: "no auto-merge PR is behind main"}, nil
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
