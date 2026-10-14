package main

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mb-89/SE/src/index"
)

func init() {
	register(Command{
		Name:    "issue edit",
		Usage:   "issue edit N [--title T] [--body B | --body-file PATH] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "rewrite se issue N's title and body, keeping its mark",
		Details: "rewrite se issue N through the same code as se issue new, never by hand: --title T replaces its title (an empty one, or one an open se issue under N's parent has already, is refused); --body B or --body-file PATH replaces its body, which still ends in se issue new's mark, <!-- se:new -->, and keeps each se block of the old body (a line holding <!-- se:KIND -->, such as the skills line or a retro's mark) whose kind the new body does not carry itself. With neither, it writes the body again as it stands, its mark put back. A pull request, or an issue not labelled se, is refused.",
		Session: true,
		Class:   batch,
		Flags: []index.Flag{
			repoFlag,
			{Name: "title", Default: "", Help: "the issue's new title `T`"},
			{Name: "body", Default: "", Help: "the issue's new body `B`"},
			{Name: "body-file", Default: "", Help: "a file `PATH` holding the issue's new body"},
		},
		Words: index.Number,
		JSON:  true,
		Run: func(c *Call) (Reply, error) {
			n, given := c.Args.Number, c.Args.Given
			title, body := c.Args.String("title"), c.Args.String("body")
			if given("body") && given("body-file") {
				return Reply{}, fmt.Errorf("issue edit takes one of --body and --body-file, not both")
			}
			var newTitle, newBody *string
			if given("title") {
				newTitle = &title
			}
			if given("body") {
				newBody = &body
			}
			if given("body-file") {
				path := c.Args.String("body-file")
				if !filepath.IsAbs(path) {
					path = filepath.Join(c.Workspace, path)
				}
				data, err := c.Disk.ReadFile(path)
				if err != nil {
					return Reply{}, err
				}
				text := string(data)
				newBody = &text
			}
			s, err := c.source()
			if err != nil {
				return Reply{}, err
			}
			if err := s.CloseParents(); err != nil {
				return Reply{}, err
			}
			ed, err := s.Edit(n, newTitle, newBody)
			if err != nil {
				return Reply{}, err
			}
			text := fmt.Sprintf("Edited #%d %s, its mark kept.\n%s", ed.Issue.Number, ed.Issue.Title, ed.Issue.URL)
			if len(ed.Kept) > 0 {
				text += "\nKept from the old body: " + strings.Join(ed.Kept, "; ")
			}
			return Reply{Text: text, Data: ed}, nil
		},
	})
}
