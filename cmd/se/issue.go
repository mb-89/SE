package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"strconv"
	"strings"

	"github.com/mb-89/SE/internal/issues"
)

// gh is how the issue commands reach GitHub; tests put recorded answers here.
var gh issues.GH = issues.Gh

func init() {
	register(Command{
		Name:    "issue next",
		Usage:   "issue next [--json] [--repo OWNER/NAME]",
		Summary: "name the next ready se issue, or say that none is ready",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue next")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			next, ok, err := s.Next()
			if err != nil {
				return Reply{}, err
			}
			return issueReply(*asJSON, next, ok, "")
		},
	})
	register(Command{
		Name:    "issue take",
		Usage:   "issue take [N] [--json] [--repo OWNER/NAME]",
		Summary: "claim the next ready se issue, or issue N: push its branch issue-N from origin/main and check it out",
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue take")
			want := 0
			// The issue's number may stand before, between or after the flags.
			for rest := c.Args; ; {
				if err := fs.Parse(rest); err != nil {
					return Reply{}, err
				}
				if fs.NArg() == 0 {
					break
				}
				n, err := strconv.Atoi(strings.TrimPrefix(fs.Arg(0), "#"))
				if err != nil || n <= 0 || want != 0 {
					return Reply{}, fmt.Errorf("issue take takes one issue number, not %q", fs.Arg(0))
				}
				want, rest = n, fs.Args()[1:]
			}
			c.Args = nil
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			took, ok, err := s.Take(c.Workspace, want)
			if err != nil {
				return Reply{}, err
			}
			return issueReply(*asJSON, took, ok, issues.Branch(took.Number))
		},
	})
}

// issueFlags is the flag set both issue commands take; src reads the issues of
// --repo, or of the workspace's origin, once the flags are parsed.
func issueFlags(c *Call, name string) (fs *flag.FlagSet, src func() (issues.Source, error), asJSON *bool) {
	fs = c.Flags(name)
	asJSON = fs.Bool("json", false, "answer JSON")
	repo := fs.String("repo", "", "the repository as OWNER/NAME (default: the workspace's origin)")
	return fs, func() (issues.Source, error) {
		if *repo == "" {
			r, err := issues.Repo(c.Workspace)
			if err != nil {
				return issues.Source{}, err
			}
			*repo = r
		}
		return issues.Source{Repo: *repo, GH: gh}, nil
	}, asJSON
}

// issueReply shows the issue, or that there was none; branch names the branch
// a take checked out.
func issueReply(asJSON bool, i issues.Issue, ok bool, branch string) (Reply, error) {
	if asJSON {
		answer := struct {
			Ready  bool          `json:"ready"`
			Issue  *issues.Issue `json:"issue,omitempty"`
			Branch string        `json:"branch,omitempty"`
		}{Ready: ok}
		if ok {
			answer.Issue, answer.Branch = &i, branch
		}
		data, err := json.Marshal(answer)
		return Reply{Text: string(data)}, err
	}
	if !ok {
		return Reply{Text: "No se issue is ready."}, nil
	}
	head := fmt.Sprintf("#%d %s\n%s", i.Number, i.Title, i.URL)
	if branch != "" {
		head = fmt.Sprintf("Took #%d %s, on branch %s.\n%s", i.Number, i.Title, branch, i.URL)
	}
	return Reply{Text: strings.TrimRight(head+"\n\n"+i.Body, "\n")}, nil
}
