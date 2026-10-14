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
		Name:    "issue supersede",
		Class:   batch,
		Usage:   "issue supersede N (--body B | --body-file PATH | --duplicate-of M) [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "close issue N by a final successor with its open questions",
		Details: "the second way a box closes the issue it took, beside a PR (and se issue close --fixed-by, where its work is on main already): create N's successor through the same code as se issue new, with N's title and text and the open questions the box could not answer (B), labelled se-final, a sub-issue of N's parent and blocked by N's open blockers; link N's open dependents as blocked by it; then close N, its comment naming the successor. A final issue is refused: its box lands a PR. A ready successor fires the routine once. With --duplicate-of M, for an issue that the open issue M (its PR) already covers, it mints nothing: it links N's open dependents as blocked by M, then closes N as a duplicate (state_reason duplicate), its comment naming M; a final issue closes so too. Before N closes, N's open PR closes, its comment naming M, and N's issue-N claim is deleted by a git push from the workspace, so se fleet fix finds no leftover claim. M is an open issue or a merged PR, never an open PR, which may never merge: an open or unmerged PR is refused, and a merged PR's commit on main is named, as se issue close --fixed-by does.",
		Session: true,
		Flags: []index.Flag{
			repoFlag,
			{Name: "body", Default: "", Help: "the open questions `B` the box could not answer"},
			{Name: "body-file", Default: "", Help: "a file `PATH` holding the open questions"},
			{Name: "duplicate-of", Default: "", Help: "the open issue or merged PR `M` that already covers N: close N as its duplicate, minting nothing"},
		},
		Words: index.Number,
		JSON:  true,
		Run: func(c *Call) (Reply, error) {
			n, body, bodyFile, dupOf := c.Args.Number, c.Args.String("body"), c.Args.String("body-file"), c.Args.String("duplicate-of")
			of := 0
			if dupOf != "" {
				if of, _ = strconv.Atoi(strings.TrimPrefix(dupOf, "#")); of <= 0 {
					return Reply{}, fmt.Errorf("--duplicate-of takes one issue number, not %q", dupOf)
				}
				if body != "" || bodyFile != "" {
					return Reply{}, fmt.Errorf("issue supersede --duplicate-of takes no open questions: the issue it duplicates carries the work on")
				}
				return duplicate(c, n, of)
			}
			if (body == "") == (bodyFile == "") {
				return Reply{}, fmt.Errorf("issue supersede takes one of --body, --body-file and --duplicate-of")
			}
			if bodyFile != "" {
				path := bodyFile
				if !filepath.IsAbs(path) {
					path = filepath.Join(c.Workspace, path)
				}
				data, err := c.Disk.ReadFile(path)
				if err != nil {
					return Reply{}, err
				}
				body = string(data)
			}
			s, err := c.source()
			if err != nil {
				return Reply{}, err
			}
			if err := s.CloseParents(); err != nil {
				return Reply{}, err
			}
			sup, err := s.Supersede(n, body)
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			if sup.Ready {
				fanout = c.fire()
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
			return Reply{
				Text: text,
				Data: struct {
					issues.Superseded
					Fanout string `json:"fanout,omitempty"`
				}{sup, fanout},
			}, nil
		},
	})
}

// duplicate closes issue n as a duplicate of the open issue of, minting
// nothing (se issue supersede n --duplicate-of of).
func duplicate(c *Call, n, of int) (Reply, error) {
	s, err := c.source()
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
	text := fmt.Sprintf("Closed #%d as a duplicate of #%d, minting nothing.\n%s", n, of, dup.URL)
	if dup.Commit != "" {
		text = fmt.Sprintf("Closed #%d as a duplicate of the merged PR #%d, its work on main in %s.\n%s", n, of, dup.Commit, dup.URL)
	}
	if len(dup.Blocks) > 0 {
		text += "\n" + numbers(dup.Blocks) + " now wait on #" + strconv.Itoa(of) + "."
	}
	for _, p := range dup.Pulls {
		text += fmt.Sprintf("\nClosed its PR #%d, naming #%d.", p, of)
	}
	if dup.Branch != "" {
		text += "\nDeleted its claim " + dup.Branch + "."
	}
	return Reply{Text: text, Data: dup}, nil
}
