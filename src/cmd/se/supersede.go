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
		Usage:   "issue supersede N (--body B | --body-file PATH | --duplicate-of M) [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "close issue N by a final successor with its open questions",
		Details: []string{
			"the second way a box closes the issue it took, beside a PR (and se issue close --fixed-by, where its work is on main already): create N's successor through the same code as se issue new, with N's title and text and the open questions the box could not answer (B), labelled se-final, a sub-issue of N's parent and blocked by N's open blockers; link N's open dependents as blocked by it; then close N, its comment naming the successor.",
			"A final issue is refused: its box lands a PR.",
			"A ready successor fires the routine once.",
			"With --duplicate-of M, for an issue that the open issue M (its PR) already covers, it mints nothing: it links N's open dependents as blocked by M, then closes N as a duplicate (state_reason duplicate), its comment naming M; a final issue closes so too.",
			"Before N closes, N's open PR closes, its comment naming M, and N's issue-N claim is deleted by a git push from the workspace, so se fleet fix finds no leftover claim.",
		},
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue supersede")
			body := fs.String("body", "", "the open questions `B` the box could not answer")
			bodyFile := fs.String("body-file", "", "a file `PATH` holding the open questions")
			dupOf := fs.String("duplicate-of", "", "the open issue `M` that already covers N: close N as its duplicate, minting nothing")
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
			of := 0
			if *dupOf != "" {
				if of, _ = strconv.Atoi(strings.TrimPrefix(*dupOf, "#")); of <= 0 {
					return Reply{}, fmt.Errorf("--duplicate-of takes one issue number, not %q", *dupOf)
				}
				if *body != "" || *bodyFile != "" {
					return Reply{}, fmt.Errorf("issue supersede --duplicate-of takes no open questions: the issue it duplicates carries the work on")
				}
				return duplicate(c, src, *asJSON, n, of)
			}
			if (*body == "") == (*bodyFile == "") {
				return Reply{}, fmt.Errorf("issue supersede takes one of --body, --body-file and --duplicate-of")
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
			sup, err := s.Supersede(n, *body)
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			if sup.Ready {
				fanout = c.fire()
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					issues.Superseded
					Fanout string `json:"fanout,omitempty"`
				}{sup, fanout})
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
		},
	})
}

// duplicate closes issue n as a duplicate of the open issue of, minting
// nothing (se issue supersede n --duplicate-of of).
func duplicate(c *Call, src func() (issues.Source, error), asJSON bool, n, of int) (Reply, error) {
	s, err := src()
	if err != nil {
		return Reply{}, err
	}
	if err := s.CloseParents(); err != nil {
		return Reply{}, err
	}
	dup, err := s.CloseDuplicate(c.Workspace, n, of)
	if err != nil {
		return Reply{}, err
	}
	if asJSON {
		data, err := json.Marshal(dup)
		return Reply{Text: string(data)}, err
	}
	text := fmt.Sprintf("Closed #%d as a duplicate of #%d, minting nothing.\n%s", n, of, dup.URL)
	if len(dup.Blocks) > 0 {
		text += "\n" + numbers(dup.Blocks) + " now wait on #" + strconv.Itoa(of) + "."
	}
	for _, p := range dup.Pulls {
		text += fmt.Sprintf("\nClosed its PR #%d, naming #%d.", p, of)
	}
	if dup.Branch != "" {
		text += "\nDeleted its claim " + dup.Branch + "."
	}
	return Reply{Text: text}, nil
}
