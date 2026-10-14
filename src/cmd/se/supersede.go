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
		Name:    "issue supersede",
		Class:   batch,
		Usage:   "issue supersede N (--body B | --body-file PATH) [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "close issue N by a final successor with its open questions",
		Details: "the second way a box closes the issue it took, beside a PR (and se issue close --fixed-by, where its work is on main already): create N's successor through the same code as se issue new, with N's title and text and the open questions the box could not answer (B), labelled se-final, a sub-issue of N's parent and blocked by N's open blockers; link N's open dependents as blocked by it; then close N, its comment naming the successor. A final issue is refused: its box lands a PR. A ready successor fires the routine once. Then it files the issue the box queued with se issue new, if any, as se issue new would create it, its body marked as N's follow-up (<!-- se:followup #N -->), names it and clears the queue; a queued issue se issue new would refuse refuses the whole command first, before anything is written.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue supersede")
			body := fs.String("body", "", "the open questions `B` the box could not answer")
			bodyFile := fs.String("body-file", "", "a file `PATH` holding the open questions")
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
				return Reply{}, fmt.Errorf("issue supersede takes one issue number, not %q", strings.Join(words, " "))
			}
			if (*body == "") == (*bodyFile == "") {
				return Reply{}, fmt.Errorf("issue supersede takes one of --body and --body-file: the open questions")
			}
			if *bodyFile != "" {
				path := *bodyFile
				if !filepath.IsAbs(path) {
					path = filepath.Join(c.Workspace, path)
				}
				data, err := c.Disk.ReadFile(path)
				if err != nil {
					return Reply{}, err
				}
				*body = string(data)
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
			sup, err := s.Supersede(n, *body)
			if err != nil {
				return Reply{}, err
			}
			return landed(c, s, n, q, *asJSON, sup.Ready, c.fire, func(filed []newAnswer, fanout string) (Reply, error) {
				if *asJSON {
					data, err := json.Marshal(struct {
						issues.Superseded
						Filed  []newAnswer `json:"filed,omitempty"`
						Fanout string      `json:"fanout,omitempty"`
					}{sup, filed, fanout})
					return Reply{Text: string(data)}, err
				}
				text := fmt.Sprintf("Superseded #%d by #%d %s, labelled %s, and closed #%d.\n%s", n, sup.Successor.Number, sup.Successor.Title, issues.FinalLabel, n, sup.Successor.URL)
				if sup.Parent > 0 {
					text += fmt.Sprintf("\nA sub-issue of #%d.", sup.Parent)
				}
				if len(sup.BlockedBy) > 0 {
					text += "\nBlocked by " + numbers(sup.BlockedBy) + "."
				}
				if len(sup.Blocks) > 0 {
					text += "\n" + numbers(sup.Blocks) + " now wait on it."
				}
				if fanout != "" {
					text += "\n" + fanout
				}
				return Reply{Text: text}, nil
			})
		},
	})
}
