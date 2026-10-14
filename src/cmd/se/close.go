package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/mb-89/SE/src/internal/issues"
)

func init() {
	register(Command{
		Name:    "issue close",
		Class:   batch,
		Usage:   "issue close N --fixed-by SHA --answers FILE [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "close issue N, its work on main already, naming the commit",
		Details: "the third way a box closes the issue it took, beside a PR and a supersede, where its work is on main already and landing would take an empty commit: refuse unless SHA names a commit that origin/main holds and FILE answers every question in spec/landing.yaml (as se issue land reads it), and refuse a closed issue and a parent; then post the answers on N, comment naming the commit, and close N as completed. Then it files the issue the box queued with se issue new, if any, as se issue new would create it, its body marked as N's follow-up (<!-- se:followup #N -->), names it and clears the queue; a queued issue se issue new would refuse refuses the whole command first, before anything is written.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue close")
			sha := fs.String("fixed-by", "", "the `SHA` of the commit on main that did N's work")
			file := fs.String("answers", "", "the landing answers, a YAML `FILE` keyed as spec/landing.yaml")
			var words []string
			for rest := c.Args; ; {
				if err := fs.Parse(rest); err != nil {
					return Reply{}, err
				}
				if fs.NArg() == 0 {
					break
				}
				words, rest = append(words, fs.Arg(0)), fs.Args()[1:]
			}
			c.Args = nil
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			n := 0
			if len(words) == 1 {
				n, _ = strconv.Atoi(strings.TrimPrefix(words[0], "#"))
			}
			if n <= 0 {
				return Reply{}, fmt.Errorf("issue close takes one issue number, not %q", strings.Join(words, " "))
			}
			if *sha == "" {
				return Reply{}, fmt.Errorf("issue close takes --fixed-by SHA: the commit on main that did #%d's work (work not on main lands with se issue land)", n)
			}
			if *file == "" {
				return Reply{}, fmt.Errorf("issue close takes --answers FILE: an answer to every question in %s", issues.QuestionsFile)
			}
			if !filepath.IsAbs(*file) {
				*file = filepath.Join(c.Workspace, *file)
			}
			qs, err := issues.Questions(c.Disk, c.Workspace)
			if err != nil {
				return Reply{}, err
			}
			answers, err := issues.ReadAnswers(c.Disk, *file)
			if err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			if err := s.CloseParents(); err != nil {
				return Reply{}, err
			}
			q, err := queued(c, s)
			if err != nil {
				return Reply{}, err
			}
			f, err := s.FixedBy(c.Workspace, c.sessionID(), n, *sha, qs, answers)
			if err != nil {
				return Reply{}, err
			}
			return closeOut(c, s, n, q, *asJSON, false, func() string { return c.fanOut(s, 0) }, func(filed []newAnswer, fanout string) (Reply, error) {
				if *asJSON {
					data, err := json.Marshal(struct {
						issues.Moot
						Filed  []newAnswer `json:"filed,omitempty"`
						Fanout string      `json:"fanout,omitempty"`
					}{f, filed, fanout})
					return Reply{Text: string(data)}, err
				}
				text := fmt.Sprintf("Closed #%d: its work is on main in %s %s; its landing answers are posted.\n%s", n, f.Commit, f.Subject, f.URL)
				if fanout != "" {
					text += "\n" + fanout
				}
				return Reply{Text: text}, nil
			})
		},
	})
}
