package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/mb-89/SE/src/internal/issues"
)

func init() {
	register(Command{
		Name:    "overhaul new",
		Usage:   "overhaul new [--unattended] [--json] [--repo OWNER/NAME]",
		Group:   "Overhaul",
		Summary: "start an overhaul: is the design still right?",
		Details: "create an overhaul: an se issue labelled se-overhaul that checks SE as it stands against every design principle, the outside world, the consistency of the whole system, the principles themselves and the retro's last 5 runs, and fire the routine so a box takes it at once. Its box creates the findings' issues, those for a person where controversial, and closes it: an overhaul never waits. --unattended records that no person started it; se issue pull --take starts one so every 5 closed retros. spec/overhaul.md has the rules.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "overhaul new")
			unattended := fs.Bool("unattended", false, "no person started it: the cadence did")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			o, err := s.NewOverhaul(*unattended)
			if err != nil {
				return Reply{}, err
			}
			fanout := fire()
			if *asJSON {
				data, err := json.Marshal(struct {
					issues.OverhaulIssue
					Fanout string `json:"fanout"`
				}{o, fanout})
				return Reply{Text: string(data)}, err
			}
			return Reply{Text: fmt.Sprintf("Created the overhaul #%d %s: its box creates the findings' issues and closes it.\n%s\n%s", o.Number, o.Title, o.URL, fanout)}, nil
		},
	})
	register(Command{
		Name:    "overhaul read",
		Usage:   "overhaul read N [--out FILE] [--json] [--repo OWNER/NAME]",
		Group:   "Overhaul",
		Summary: "read an overhaul's facts and write its report draft",
		Details: "read overhaul N's facts and write its report draft to FILE (default: ../overhaul-N.md beside the workspace): every design principle from spec/principles.md, mechanical or judged; the last 5 retros' metrics, broken rule checks and findings, how many became issues and closed, and which recurred; and the previous overhaul's findings with their issues' state. Where a report is already posted on N (an overhaul from before overhauls stopped waiting for the owner), it writes that one instead, to be filed as it stands.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "overhaul read")
			out := fs.String("out", "", "where to write the draft, a `FILE` (default: ../overhaul-N.md beside the workspace)")
			n, err := numbered(c, fs, "overhaul read")
			if err != nil {
				return Reply{}, err
			}
			path := draftPath(c, *out, "overhaul", n)
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			posted, err := s.PostedOverhaul(n)
			if err != nil {
				return Reply{}, err
			}
			text, what := posted, "the report posted on it: apply what the owner said in its comments, if anything, to its block, then run se overhaul file"
			if posted == "" {
				ps, err := issues.Principles(c.Workspace)
				if err != nil {
					return Reply{}, err
				}
				r, err := s.CollectOverhaul(n, ps)
				if err != nil {
					return Reply{}, err
				}
				if text, err = r.OverhaulDraft(); err != nil {
					return Reply{}, err
				}
				what = fmt.Sprintf("its draft: %d principles to judge, %d retros' reports", len(r.Principles), len(r.Retros))
			}
			if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Overhaul int    `json:"overhaul"`
					Draft    string `json:"draft"`
					Posted   bool   `json:"posted"`
				}{n, path, posted != ""})
				return Reply{Text: string(data)}, err
			}
			return Reply{Text: fmt.Sprintf("Wrote the overhaul #%d's report to %s: %s.", n, path, what)}, nil
		},
	})
	register(Command{
		Name:    "overhaul file",
		Usage:   "overhaul file N [--draft FILE] [--json] [--repo OWNER/NAME]",
		Group:   "Overhaul",
		Summary: "file a judged report: create its issues and close it",
		Details: "file overhaul N's report from its judged draft FILE (default: ../overhaul-N.md beside the workspace). It refuses a judgment that is not complete: a principle without a verdict, nothing said on the outside world, the system's consistency, the principles themselves, the retro, speed, mechanizing or removal, a finding without its principle, place or how far it strays, an outside finding without a source. A change to a principle is always controversial. It gets one se issue per finding, one for a person (se-person) where it is controversial, then the report as its closing comment, and closes: it never waits for the owner. Its claim issue-N goes.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "overhaul file")
			file := fs.String("draft", "", "the judged draft, a `FILE` (default: ../overhaul-N.md beside the workspace)")
			n, err := numbered(c, fs, "overhaul file")
			if err != nil {
				return Reply{}, err
			}
			data, err := os.ReadFile(draftPath(c, *file, "overhaul", n))
			if err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			filed, err := s.FileOverhaul(n, string(data))
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
			text := fmt.Sprintf("Created %d issue(s) from the overhaul #%d's findings, %d of them for a person: %s. The report is its closing comment, and it is closed.", len(filed.Issues), n, len(filed.Person), numbers(filed.Issues))
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
