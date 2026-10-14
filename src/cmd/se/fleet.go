package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mb-89/SE/src/internal/io/github"
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
		Details: "read GitHub and list every finding: a stalled root, a conflicted, red or green but unmerged PR, a claim with no PR, a leftover claim, an impossible block, an issue waiting on a person. Each names its issue, its PR and its remedy, in the order the box, se:coordinator, fixes them. Nothing found, it says healthy. Where GitHub's answers say the hour's quota of requests has fallen below the github instance's quota-floor share (github/config/quota-floor), a last line says how many are left and when it resets. With fan-out on, a fan-out the routine refused with 429, which se issue pull --take keeps on the alive claims with its retry time, fires once that time has passed and the fleet still needs the box, and a last line says so. spec/coordination.md has the rules.",
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
			// The quota, as GitHub's answers to these reads gave it.
			_, rate := github.Metered(c.GitHub)
			quota := rate.Low(githubSettings().Floor)
			if *asJSON {
				data, err := json.Marshal(struct {
					Healthy  bool             `json:"healthy"`
					Findings []issues.Finding `json:"findings"`
					Fanout   string           `json:"fanout,omitempty"`
					Quota    string           `json:"quota,omitempty"`
				}{len(found) == 0, append([]issues.Finding{}, found...), fanout, quota})
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
			if quota != "" {
				lines = append(lines, quota)
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
		Details: "list every issue-<n> branch whose issue is closed and every claude/* branch whose last commit is more than an hour old, each with no open PR, and every issue-<n> branch whose issue closed as a duplicate, with its open PR. --apply deletes them, closing such a PR unmerged first with a comment that says why; without it nothing is written. It never touches main or any other branch. The prune workflow runs it with the repository's token.",
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
		Class:   batch,
		Usage:   "fleet refresh [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "merge main into each auto-merge PR behind it and rerun its CI",
		Details: "for every open PR against main with auto-merge on whose head main has moved past: merge main into it through GitHub's update-branch and start the ci workflow on its new head, since main's ruleset merges a PR only when it is up to date with main and the repository's token starts no CI by its pushes. A PR that conflicts with main is left to its takeover. A PR whose update fails is reported, and the others are still updated. The refresh workflow runs it with the repository's token on every push to main.",
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
	register(Command{
		Name:    "fleet rules",
		Usage:   "fleet rules [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Class:   batch,
		Summary: "tell each open se PR the se checks it breaks merged with main",
		Details: "for every open se PR against main: merge its head with origin's main in a worktree under .se/.runtime/rules, build se there and run se rules and the tests of the battery, the budgets and the programs list on the merge, and comment on each PR it breaks the findings and what to do, once for the same findings, so the box that owns it acts before its CI goes red. A PR that conflicts with main is left to its takeover; one whose check fails is reported, and the others are still checked. The rules workflow runs it when main takes a change to se's rules, tests/check.sh, the battery, spec/budgets.yaml or proc.",
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

// MergeTests are the Go packages whose tests se fleet rules runs on each
// merge beside se rules: those that read tests/check.sh's steps,
// spec/budgets.yaml's budgets and proc.Programs, which a PR opened before
// main changed them breaks without breaking a rule. The rules workflow
// triggers on each of their sources (rulesWorkflowPaths).
var mergeTests = []string{"./cmd/se", "./internal/battery/...", "./internal/io/proc/..."}

// rulesWorkflowPaths are the paths whose change on main runs se fleet rules:
// se's rules, and what mergeTests check.
var rulesWorkflowPaths = []string{"src/internal/rules/**", "tests/check.sh", "src/internal/battery/**", "spec/budgets.yaml", "src/internal/io/proc/**"}

// rulesOn builds se from the checkout at dir and runs its se rules and the
// tests of mergeTests there, answering the findings without their timings;
// empty where both pass. A checkout that does not build answers that as its
// finding.
func rulesOn(procs proc.Procs, dir string) (string, error) {
	bin := filepath.Join(dir, ".se", ".runtime", "se-rules")
	if out, err := proc.Combined(procs, proc.Cmd{Name: "go", Args: []string{"-C", filepath.Join(dir, "src"), "build", "-o", bin, "./cmd/se"}}); err != nil {
		if _, ok := proc.ExitCode(err); !ok {
			return "", fmt.Errorf("go build: %w", err)
		}
		return "it does not build:\n" + strings.TrimSpace(string(out)), nil
	}
	var found []string
	out, err := proc.Combined(procs, proc.Cmd{Name: bin, Args: []string{"rules", "--workspace", dir}, Dir: dir})
	if err != nil {
		if _, ok := proc.ExitCode(err); !ok {
			return "", fmt.Errorf("se rules: %w", err)
		}
		found = append(found, rulesFindings(string(out)))
	}
	out, err = proc.Combined(procs, proc.Cmd{Name: "go", Args: append([]string{"-C", filepath.Join(dir, "src"), "test"}, mergeTests...)})
	if err != nil {
		if _, ok := proc.ExitCode(err); !ok {
			return "", fmt.Errorf("go test: %w", err)
		}
		found = append(found, testFindings(string(out)))
	}
	return strings.Join(found, "\n"), nil
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

// testTiming is a duration go test prints after a test or a package.
var testTiming = regexp.MustCompile(`(\s+\(\d+(\.\d+)?s\)|\t\d+(\.\d+)?s|\t\(cached\))$`)

// testFindings is go test's failing output without its passing packages and
// its timings, which change from run to run while the failures stay.
func testFindings(out string) string {
	var kept []string
	for _, l := range strings.Split(strings.TrimSpace(out), "\n") {
		if !strings.HasPrefix(l, "ok ") {
			kept = append(kept, testTiming.ReplaceAllString(l, ""))
		}
	}
	return "go test " + strings.Join(mergeTests, " ") + ":\n" + strings.Join(kept, "\n")
}

// findingText is one finding: its kind and issue, what is wrong, and its remedy.
func findingText(f issues.Finding) string {
	head := fmt.Sprintf("%s #%d", f.Kind, f.Issue)
	if f.PR > 0 {
		head += fmt.Sprintf(" (PR #%d)", f.PR)
	}
	return fmt.Sprintf("%s: %s\n  remedy: %s", head, f.What, f.Remedy)
}
