package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"path/filepath"
	"strconv"
	"strings"
)

func init() {
	register(Command{
		Name:    "issue edit",
		Usage:   "issue edit N [--title T] [--body B | --body-file PATH] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "rewrite se issue N's title and body, keeping its mark",
		Details: []string{
			"rewrite se issue N through the same code as se issue new, never by hand: --title T replaces its title (an empty one, or one an open se issue under N's parent has already, is refused); --body B or --body-file PATH replaces its body, which still ends in se issue new's mark, <!-- se:new -->, and keeps each se block of the old body (a line holding <!-- se:KIND -->, such as the skills line or a retro's mark) whose kind the new body does not carry itself.",
			"With neither, it writes the body again as it stands, its mark put back.",
			"A pull request, or an issue not labelled se, is refused.",
		},
		Session: true,
		Class:   batch,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue edit")
			title := fs.String("title", "", "the issue's new title `T`")
			body := fs.String("body", "", "the issue's new body `B`")
			bodyFile := fs.String("body-file", "", "a file `PATH` holding the issue's new body")
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
				return Reply{}, fmt.Errorf("issue edit takes one issue number, not %q", strings.Join(words, " "))
			}
			given := map[string]bool{}
			fs.Visit(func(f *flag.Flag) { given[f.Name] = true })
			if given["body"] && given["body-file"] {
				return Reply{}, fmt.Errorf("issue edit takes one of --body and --body-file, not both")
			}
			var newTitle, newBody *string
			if given["title"] {
				newTitle = title
			}
			if given["body"] {
				newBody = body
			}
			if given["body-file"] {
				path := *bodyFile
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
			s, err := src()
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
			if *asJSON {
				data, err := json.Marshal(ed)
				return Reply{Text: string(data)}, err
			}
			text := fmt.Sprintf("Edited #%d %s, its mark kept.\n%s", ed.Issue.Number, ed.Issue.Title, ed.Issue.URL)
			if len(ed.Kept) > 0 {
				text += "\nKept from the old body: " + strings.Join(ed.Kept, "; ")
			}
			return Reply{Text: text}, nil
		},
	})
}
