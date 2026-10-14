package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/mb-89/SE/src/internal/issues"
)

func init() {
	register(Command{
		Name:    "retro new",
		Usage:   "retro new (--field TEXT | --no-field | --unattended) [--json] [--repo OWNER/NAME]",
		Group:   "Retro",
		Summary: "start a retro over everything closed since the last one",
		Details: "create a retro: an se issue labelled se-retro, whose window is everything closed since the last retro closed, and fire the routine so a box takes it at once. A person starts it with --field TEXT, their field feedback, which goes into the issue (the retro skill asks for it), or --no-field. --unattended never asks. Either way its box creates the findings' issues, those for a person where controversial, and closes it: a retro never waits. spec/retro.md has the rules.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "retro new")
			field := fs.String("field", "", "the person's field feedback, as `TEXT`")
			fs.Bool("no-field", false, "a person starts it without field feedback")
			unattended := fs.Bool("unattended", false, "no person started it: never ask for field feedback")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			given := map[string]bool{}
			fs.Visit(func(f *flag.Flag) { given[f.Name] = true })
			if btoi(given["field"])+btoi(given["no-field"])+btoi(given["unattended"]) != 1 {
				return Reply{}, fmt.Errorf("retro new takes one of --field TEXT (ask the person for their field feedback), --no-field and --unattended")
			}
			if given["field"] && strings.TrimSpace(*field) == "" {
				return Reply{}, fmt.Errorf("--field takes the person's feedback; without any, say --no-field")
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			r, err := s.NewRetro(*field, *unattended)
			if err != nil {
				return Reply{}, err
			}
			fanout := fire()
			if *asJSON {
				data, err := json.Marshal(struct {
					issues.RetroIssue
					Fanout string `json:"fanout"`
				}{r, fanout})
				return Reply{Text: string(data)}, err
			}
			window := "the whole history: no retro has closed yet"
			if r.Previous > 0 {
				window = fmt.Sprintf("everything closed since #%d closed", r.Previous)
			}
			return Reply{Text: fmt.Sprintf("Created the retro #%d %s, over %s.\n%s\n%s", r.Number, r.Title, window, r.URL, fanout)}, nil
		},
	})
	register(Command{
		Name:    "retro collect",
		Usage:   "retro collect N [--out FILE] [--json] [--repo OWNER/NAME]",
		Group:   "Retro",
		Summary: "read a retro's window from GitHub and write its report draft",
		Details: "read retro N's window from GitHub (everything closed since the last retro closed) and write the report draft to FILE (default: ../retro-N.md beside the workspace): the rule checks, the counts, the metrics against the previous retros, how the previous retro's findings fared, the scripts added under src/scripts/, and the matrix of every closed issue × every landing question. Where a report is already posted on N (a retro from before retros stopped waiting for the owner), it writes that one instead, to be filed as it stands.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "retro collect")
			out := fs.String("out", "", "where to write the draft, a `FILE` (default: ../retro-N.md beside the workspace)")
			n, err := numbered(c, fs, "retro collect")
			if err != nil {
				return Reply{}, err
			}
			path := draftPath(c, *out, "retro", n)
			s, err := src()
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
			if *asJSON {
				data, err := json.Marshal(struct {
					Retro  int    `json:"retro"`
					Draft  string `json:"draft"`
					Posted bool   `json:"posted"`
				}{n, path, posted != ""})
				return Reply{Text: string(data)}, err
			}
			return Reply{Text: fmt.Sprintf("Wrote the retro #%d's report to %s: %s.", n, path, what)}, nil
		},
	})
	register(Command{
		Name:    "retro report",
		Usage:   "retro report N [--draft FILE] [--json] [--repo OWNER/NAME]",
		Group:   "Retro",
		Summary: "file a judged report: create its issues and close it",
		Details: "file retro N's report from its judged draft FILE (default: ../retro-N.md beside the workspace). It refuses a judgment that is not complete. It gets one se issue per finding, one for a person (se-person) where it is controversial, then the report as its closing comment, and closes: it never waits for the owner. Its claim issue-N goes.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "retro report")
			file := fs.String("draft", "", "the judged draft, a `FILE` (default: ../retro-N.md beside the workspace)")
			n, err := numbered(c, fs, "retro report")
			if err != nil {
				return Reply{}, err
			}
			data, err := c.Disk.ReadFile(draftPath(c, *file, "retro", n))
			if err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			filed, err := s.FileReport(n, string(data))
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			if filed.Ready {
				fanout = fire()
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					issues.Filed
					Fanout string `json:"fanout,omitempty"`
				}{filed, fanout})
				return Reply{Text: string(data)}, err
			}
			text := fmt.Sprintf("Created %d issue(s) from the retro #%d's findings, %d of them for a person: %s. The report is its closing comment, and it is closed.", len(filed.Issues), n, len(filed.Person), numbers(filed.Issues))
			if filed.Left != "" {
				text += "\n" + filed.Left + "."
			}
			if fanout != "" {
				text += "\n" + fanout
			}
			return Reply{Text: text}, nil
		},
	})
}

func btoi(b bool) int {
	if b {
		return 1
	}
	return 0
}

// numbered parses a command that takes one issue number among its flags.
func numbered(c *Call, fs *flag.FlagSet, name string) (int, error) {
	var words []string
	for rest := c.Args; ; {
		if err := fs.Parse(rest); err != nil {
			return 0, err
		}
		if fs.NArg() == 0 {
			break
		}
		words, rest = append(words, fs.Arg(0)), fs.Args()[1:]
	}
	c.Args = nil
	if err := c.Parse(fs); err != nil {
		return 0, err
	}
	n := 0
	if len(words) == 1 {
		n, _ = strconv.Atoi(strings.TrimPrefix(words[0], "#"))
	}
	if n <= 0 {
		return 0, fmt.Errorf("%s takes one issue number, not %q", name, strings.Join(words, " "))
	}
	return n, nil
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
