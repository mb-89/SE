package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/issues"
)

func init() {
	register(Command{
		Name:    "fleet check",
		Class:   interactive,
		Usage:   "fleet check [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "list what is broken in the fleet, each with its remedy",
		Details: "read GitHub and list every finding: a stalled root, a conflicted, red or green but unmerged PR, a claim with no PR, a leftover claim, an impossible block, an issue waiting on a person. Each names its issue, its PR and its remedy, in the order the box, se:coordinator, fixes them. Nothing found, it says healthy. With fan-out on, a fan-out the routine refused with 429, which se issue pull --take keeps on the alive claims with its retry time, fires once that time has passed and the fleet still needs the box, and a last line says so. spec/coordination.md has the rules.",
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
		Class:   batch,
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
		Class:   batch,
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
		Name:    "fleet trust",
		Class:   batch,
		Usage:   "fleet trust --sha SHA --tree TREE [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "say whether CI may trust the battery a box ran on a commit",
		Details: fmt.Sprintf("CI's check job asks it first: exit 0 and say why where commit SHA's latest %s status is a success naming TREE, the tree CI checked out, posted by an account with write access to the repository, as se issue land and se issue keep post it on the commit they pushed; else exit 1 and say why, and CI runs the battery itself (with --json, a trusted commit answers {\"trusted\",\"why\"}). A status not posted yet is asked for again a few times. It is trust in one's own boxes, not a proof.", issues.BatteryContext),
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "fleet trust")
			sha := fs.String("sha", "", "the `SHA` of the PR's head commit")
			tree := fs.String("tree", "", "the `TREE` CI checked out, HEAD^{tree}")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			if *sha == "" || *tree == "" {
				return Reply{}, fmt.Errorf("fleet trust takes --sha SHA and --tree TREE")
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			why, err := s.Trusted(*sha, *tree)
			if err != nil {
				return Reply{}, fmt.Errorf("not trusted, so CI runs the battery: %w", err)
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Trusted bool   `json:"trusted"`
					Why     string `json:"why"`
				}{true, why})
				return Reply{Text: string(data)}, err
			}
			return Reply{Text: "trusted: " + why}, nil
		},
	})
	register(Command{
		Name:    "fleet rules",
		Usage:   "fleet rules [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Class:   batch,
		Summary: "tell each open se PR the se rules it breaks merged with main",
		Details: "for every open se PR against main: merge its head with origin's main in a worktree under .se/.runtime/rules, build se there and run se rules on the merge, and comment on each PR it breaks the findings and what to do, once for the same findings, so the box that owns it acts before its CI goes red. A PR that conflicts with main is left to its takeover; one whose check fails is reported, and the others are still checked. The rules workflow runs it when main takes a change to se's rules.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "fleet rules")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			done, rulesErr := s.Rules(c.Workspace, func(dir string) (string, error) { return rulesOn(c.Proc, dir) })
			lines := make([]string, len(done))
			for k, r := range done {
				lines[k] = fmt.Sprintf("PR #%d (%s at %s): %s", r.PR, r.Branch, r.Head, r.Did)
				if r.Findings != "" {
					lines[k] += "\n  " + strings.ReplaceAll(r.Findings, "\n", "\n  ")
				}
			}
			if rulesErr != nil {
				return Reply{}, fmt.Errorf("%w\n%s", rulesErr, strings.Join(lines, "\n"))
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Ruled []issues.Ruled `json:"ruled"`
				}{append([]issues.Ruled{}, done...)})
				return Reply{Text: string(data)}, err
			}
			if len(done) == 0 {
				return Reply{Text: "no open se PR"}, nil
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
}

// rulesOn builds se from the checkout at dir and runs its se rules there,
// answering the findings, one per line, without the rules' timings; empty
// where it passes. A checkout that does not build answers that as its finding.
func rulesOn(procs proc.Procs, dir string) (string, error) {
	bin := filepath.Join(dir, ".se", ".runtime", "se-rules")
	if out, err := proc.Combined(procs, proc.Cmd{Name: "go", Args: []string{"-C", filepath.Join(dir, "src"), "build", "-o", bin, "./cmd/se"}}); err != nil {
		if _, ok := proc.ExitCode(err); !ok {
			return "", fmt.Errorf("go build: %w", err)
		}
		return "it does not build:\n" + strings.TrimSpace(string(out)), nil
	}
	out, err := proc.Combined(procs, proc.Cmd{Name: bin, Args: []string{"rules", "--workspace", dir}, Dir: dir})
	if err == nil {
		return "", nil
	}
	if _, ok := proc.ExitCode(err); !ok {
		return "", fmt.Errorf("se rules: %w", err)
	}
	return rulesFindings(string(out)), nil
}

// rulesFindings is se rules' failing output without its timings, which
// change from run to run while the findings stay.
func rulesFindings(out string) string {
	var kept []string
	for _, l := range strings.Split(strings.TrimSpace(out), "\n") {
		if !strings.HasPrefix(l, "check: rule ") {
			kept = append(kept, l)
		}
	}
	return strings.Join(kept, "\n")
}

// findingText is one finding: its kind and issue, what is wrong, and its remedy.
func findingText(f issues.Finding) string {
	head := fmt.Sprintf("%s #%d", f.Kind, f.Issue)
	if f.PR > 0 {
		head += fmt.Sprintf(" (PR #%d)", f.PR)
	}
	return fmt.Sprintf("%s: %s\n  remedy: %s", head, f.What, f.Remedy)
}
