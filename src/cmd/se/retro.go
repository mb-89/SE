package main

import (
	"fmt"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/issues"
)

func init() {
	register(Command{
		Name:    "retro new",
		Class:   batch,
		Usage:   "retro new (--field TEXT | --no-field | --unattended) [--json] [--repo OWNER/NAME]",
		Group:   "Retro",
		Summary: "start a retro over everything closed since the last one",
		Details: "create a retro: an se issue labelled se-retro, whose window is everything closed since the last retro closed, and fire the routine so a box takes it at once. A person starts it with --field TEXT, their field feedback, which goes into the issue (the agent se:retro passes it on), or --no-field. --unattended never asks. Either way its box creates the findings' issues, those for a person where controversial, and closes it: a retro never waits. spec/retro.md has the rules.",
		Session: true,
		Flags: []index.Flag{
			repoFlag,
			{Name: "field", Default: "", Help: "the person's field feedback, as `TEXT`"},
			{Name: "no-field", Default: false, Help: "a person starts it without field feedback"},
			{Name: "unattended", Default: false, Help: "no person started it: never ask for field feedback"},
		},
		JSON: true,
		Run: func(c *Call) (Reply, error) {
			field, given := c.Args.String("field"), c.Args.Given
			if btoi(given("field"))+btoi(given("no-field"))+btoi(given("unattended")) != 1 {
				return Reply{}, fmt.Errorf("retro new takes one of --field TEXT (ask the person for their field feedback), --no-field and --unattended")
			}
			if given("field") && strings.TrimSpace(field) == "" {
				return Reply{}, fmt.Errorf("--field takes the person's feedback; without any, say --no-field")
			}
			s, err := c.source()
			if err != nil {
				return Reply{}, err
			}
			r, err := s.NewRetro(field, c.Args.Bool("unattended"))
			if err != nil {
				return Reply{}, err
			}
			fanout := c.fire()
			window := "the whole history: no retro has closed yet"
			if r.Previous > 0 {
				window = fmt.Sprintf("everything closed since #%d closed", r.Previous)
			}
			return Reply{
				Text: fmt.Sprintf("Created the retro #%d %s, over %s.\n%s\n%s", r.Number, r.Title, window, r.URL, fanout),
				Data: struct {
					issues.RetroIssue
					Fanout string `json:"fanout"`
				}{r, fanout},
			}, nil
		},
	})
	register(Command{
		Name:    "retro collect",
		Class:   batch,
		Usage:   "retro collect N [--out FILE] [--json] [--repo OWNER/NAME]",
		Group:   "Retro",
		Summary: "read a retro's window from GitHub and write its report draft",
		Details: "read retro N's window from GitHub (everything closed since the last retro closed) and write the report draft to FILE (default: ../retro-N.md beside the workspace): the rule checks, the counts, the metrics against the previous retros, how the previous retro's findings fared, the scripts added under src/scripts/, and the matrix of every closed issue × every landing question. Where a report is already posted on N (a retro from before retros stopped waiting for the owner), it writes that one instead, to be filed as it stands.",
		Session: true,
		Flags:   []index.Flag{repoFlag, {Name: "out", Default: "", Help: "where to write the draft, a `FILE` (default: ../retro-N.md beside the workspace)"}},
		Words:   index.Number,
		JSON:    true,
		Run: func(c *Call) (Reply, error) {
			n := c.Args.Number
			path := draftPath(c, c.Args.String("out"), "retro", n)
			s, err := c.source()
			if err != nil {
				return Reply{}, err
			}
			posted, err := s.Posted(n)
			if err != nil {
				return Reply{}, err
			}
			text, what := posted, "the report posted on it: apply what the owner said in its comments, if anything, to its block, then run se retro report"
			var col issues.Collected
			if posted == "" {
				qs, err := issues.Questions(c.Disk, c.Workspace)
				if err != nil {
					return Reply{}, err
				}
				if col, err = s.Collect(n); err != nil {
					return Reply{}, err
				}
				if text, err = col.Draft(qs); err != nil {
					return Reply{}, err
				}
				what = fmt.Sprintf("its draft: %d closed issues, %d merged PRs, %d broken rule checks", len(col.Rows), col.PRs, len(col.Checks))
			}
			if err := c.Disk.WriteFile(path, []byte(text)); err != nil {
				return Reply{}, err
			}
			return Reply{
				Text: fmt.Sprintf("Wrote the retro #%d's report to %s: %s.", n, path, what),
				Data: struct {
					Retro  int    `json:"retro"`
					Draft  string `json:"draft"`
					Posted bool   `json:"posted"`
				}{n, path, posted != ""},
			}, nil
		},
	})
	register(Command{
		Name:    "retro report",
		Class:   batch,
		Usage:   "retro report N [--draft FILE] [--json] [--repo OWNER/NAME]",
		Group:   "Retro",
		Summary: "file a judged report: create its issues and close it",
		Details: "file retro N's report from its judged draft FILE (default: ../retro-N.md beside the workspace). It refuses a judgment that is not complete. It gets one se issue per finding, one for a person (se-person) where it is controversial, then the report as its closing comment, and closes: it never waits for the owner. Its claim issue-N goes.",
		Session: true,
		Flags:   []index.Flag{repoFlag, {Name: "draft", Default: "", Help: "the judged draft, a `FILE` (default: ../retro-N.md beside the workspace)"}},
		Words:   index.Number,
		JSON:    true,
		Run: func(c *Call) (Reply, error) {
			n := c.Args.Number
			data, err := c.Disk.ReadFile(draftPath(c, c.Args.String("draft"), "retro", n))
			if err != nil {
				return Reply{}, err
			}
			s, err := c.source()
			if err != nil {
				return Reply{}, err
			}
			filed, err := s.FileReport(n, string(data))
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			if filed.Ready {
				fanout = c.fire()
			}
			text := fmt.Sprintf("Created %d issue(s) from the retro #%d's findings, %d of them for a person: %s. The report is its closing comment, and it is closed.", len(filed.Issues), n, len(filed.Person), numbers(filed.Issues))
			if filed.Left != "" {
				text += "\n" + filed.Left + "."
			}
			if fanout != "" {
				text += "\n" + fanout
			}
			return Reply{Text: text, Data: filedData(filed, fanout)}, nil
		},
	})
}

func btoi(b bool) int {
	if b {
		return 1
	}
	return 0
}

// filedData is a filed report as data: its issues and the fan-out it fired.
func filedData(filed issues.Filed, fanout string) any {
	return struct {
		issues.Filed
		Fanout string `json:"fanout,omitempty"`
	}{filed, fanout}
}

// draftPath is where the draft of a run (a retro, an overhaul) lives: FILE,
// relative to the workspace, or ../KIND-N.md beside it, so the checkout stays
// clean.
func draftPath(c *Call, file, kind string, n int) string {
	if file == "" {
		return filepath.Join(filepath.Dir(c.Workspace), fmt.Sprintf("%s-%d.md", kind, n))
	}
	if filepath.IsAbs(file) {
		return file
	}
	return filepath.Join(c.Workspace, file)
}

func numbers(ns []int) string {
	if len(ns) == 0 {
		return "none"
	}
	out := make([]string, len(ns))
	for k, n := range ns {
		out[k] = "#" + strconv.Itoa(n)
	}
	return strings.Join(out, ", ")
}
