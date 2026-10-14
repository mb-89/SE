package main

import (
	"fmt"
	"regexp"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/issues"
	"github.com/mb-89/SE/src/internal/shape"
)

func init() {
	register(Command{
		Name:    "overhaul new",
		Class:   batch,
		Usage:   "overhaul new [--unattended] [--json] [--repo OWNER/NAME]",
		Group:   "Overhaul",
		Summary: "start an overhaul: is the design still right?",
		Details: fmt.Sprintf("create an overhaul: an se issue labelled se-overhaul that checks SE as it stands against every design principle, the outside world, the consistency of the whole system, the principles themselves and the retro's last %d runs (issues/config/overhaul-cadence), and fire the routine so a box takes it at once. Its box creates the findings' issues, those for a person where controversial, and closes it: an overhaul never waits. --unattended records that no person started it; se issue pull --take starts one so every %d closed retros. spec/overhaul.md has the rules.", issueConfig().OverhaulCadence, issueConfig().OverhaulCadence),
		Session: true,
		Flags:   []index.Flag{repoFlag, {Name: "unattended", Default: false, Help: "no person started it: the cadence did"}},
		JSON:    true,
		Run: func(c *Call) (Reply, error) {
			s, err := c.source()
			if err != nil {
				return Reply{}, err
			}
			o, err := s.NewOverhaul(c.Args.Bool("unattended"))
			if err != nil {
				return Reply{}, err
			}
			fanout := c.fire()
			return Reply{
				Text: fmt.Sprintf("Created the overhaul #%d %s: its box creates the findings' issues and closes it.\n%s\n%s", o.Number, o.Title, o.URL, fanout),
				Data: struct {
					issues.OverhaulIssue
					Fanout string `json:"fanout"`
				}{o, fanout},
			}, nil
		},
	})
	register(Command{
		Name:    "overhaul read",
		Class:   batch,
		Usage:   "overhaul read N [--out FILE] [--json] [--repo OWNER/NAME]",
		Group:   "Overhaul",
		Summary: "read an overhaul's facts and write its report draft",
		Details: fmt.Sprintf("read overhaul N's facts and write its report draft to FILE (default: ../overhaul-N.md beside the workspace): every design principle from spec/principles.md, mechanical or judged; the last %d retros' metrics (issues/config/overhaul-cadence), broken rule checks and findings, how many became issues and closed, and which recurred; the previous overhaul's findings with their issues' state; and the pruning and code-shape facts of the workspace's code (production-unreachable, duplicates and near-duplicates, sizes, one-user abstractions, unused se surfaces, legacy states, scripts, the files untouched longest, the longest functions, files and parameter lists, switches on a kind, and files touched per change). Where a report is already posted on N (an overhaul from before overhauls stopped waiting for the owner), it writes that one instead, to be filed as it stands.", issueConfig().OverhaulCadence),
		Session: true,
		Flags:   []index.Flag{repoFlag, {Name: "out", Default: "", Help: "where to write the draft, a `FILE` (default: ../overhaul-N.md beside the workspace)"}},
		Words:   index.Number,
		JSON:    true,
		Run: func(c *Call) (Reply, error) {
			n := c.Args.Number
			path := draftPath(c, c.Args.String("out"), "overhaul", n)
			s, err := c.source()
			if err != nil {
				return Reply{}, err
			}
			posted, err := s.PostedOverhaul(n)
			if err != nil {
				return Reply{}, err
			}
			text, what := posted, "the report posted on it: apply what the owner said in its comments, if anything, to its block, then run se overhaul file"
			if posted == "" {
				ps, err := issues.Principles(c.Disk, c.Workspace)
				if err != nil {
					return Reply{}, err
				}
				r, err := s.CollectOverhaul(n, ps)
				if err != nil {
					return Reply{}, err
				}
				r.Code = codeFacts(c, r.Window)
				if text, err = r.OverhaulDraft(); err != nil {
					return Reply{}, err
				}
				what = fmt.Sprintf("its draft: %d principles to judge, %d retros' reports", len(r.Principles), len(r.Retros))
			}
			if err := c.Disk.WriteFile(path, []byte(text)); err != nil {
				return Reply{}, err
			}
			return Reply{
				Text: fmt.Sprintf("Wrote the overhaul #%d's report to %s: %s.", n, path, what),
				Data: struct {
					Overhaul int    `json:"overhaul"`
					Draft    string `json:"draft"`
					Posted   bool   `json:"posted"`
				}{n, path, posted != ""},
			}, nil
		},
	})
	register(Command{
		Name:    "overhaul file",
		Class:   batch,
		Usage:   "overhaul file N [--draft FILE] [--json] [--repo OWNER/NAME]",
		Group:   "Overhaul",
		Summary: "file a judged report: create its issues and close it",
		Details: "file overhaul N's report from its judged draft FILE (default: ../overhaul-N.md beside the workspace). It refuses a judgment that is not complete: a principle without a verdict, nothing said on the outside world, the system's consistency, the principles themselves, the retro, speed, mechanizing or removal, a finding without its principle, place or how far it strays, an outside finding without a source. A change to a principle is always controversial. It gets one se issue per finding, one for a person (se-person) where it is controversial, then the report as its closing comment, and closes: it never waits for the owner. Its claim issue-N goes.",
		Session: true,
		Flags:   []index.Flag{repoFlag, {Name: "draft", Default: "", Help: "the judged draft, a `FILE` (default: ../overhaul-N.md beside the workspace)"}},
		Words:   index.Number,
		JSON:    true,
		Run: func(c *Call) (Reply, error) {
			n := c.Args.Number
			data, err := c.Disk.ReadFile(draftPath(c, c.Args.String("draft"), "overhaul", n))
			if err != nil {
				return Reply{}, err
			}
			s, err := c.source()
			if err != nil {
				return Reply{}, err
			}
			filed, err := s.FileOverhaul(n, string(data))
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			if filed.Ready {
				fanout = c.fire()
			}
			text := fmt.Sprintf("Created %d issue(s) from the overhaul #%d's findings, %d of them for a person: %s. The report is its closing comment, and it is closed.", len(filed.Issues), n, len(filed.Person), numbers(filed.Issues))
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

// flagNamed is a flag in a command's usage.
var flagNamed = regexp.MustCompile(`--([a-z][a-z-]*)`)

// codeFacts are the pruning and code-shape facts of the workspace's code,
// with the commands and flags registered and what GitHub said in w. They are
// advice: what cannot be read is said in their place.
func codeFacts(c *Call, w issues.OverhaulWindow) string {
	in, err := shape.Read(c.Disk, c.Proc, c.Workspace)
	if err != nil {
		return "## Pruning and code shape\nNot read: " + err.Error() + ".\n"
	}
	for _, name := range sortedNames() {
		sur := shape.Surface{Name: name}
		for _, m := range flagNamed.FindAllStringSubmatch(commands[name].Usage, -1) {
			sur.Flags = append(sur.Flags, m[1])
		}
		in.Commands = append(in.Commands, sur)
	}
	in.Answers, in.Since, in.ReadBy = w.Answers, w.Since, w.ReadBy
	return shape.Find(in).Markdown()
}
