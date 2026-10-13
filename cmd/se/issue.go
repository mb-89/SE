package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/mb-89/SE/internal/issues"
)

// gh is how the issue commands reach GitHub; tests put recorded answers here.
var gh issues.GH = issues.Gh

// fire is the fan-out after a claim: it fires the routine once and answers a
// line saying what happened. Tests put a fake here.
var fire = issues.FireFromEnv

// check is what issue land runs before it pushes: the repo's one definition of
// green. It answers the check's output when it fails.
var check = func(dir string) error {
	cmd := exec.Command("sh", "./tests/check.sh")
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		lines := strings.Split(strings.TrimRight(string(out), "\n"), "\n")
		if len(lines) > 40 {
			lines = lines[len(lines)-40:]
		}
		return fmt.Errorf("sh ./tests/check.sh: %v\n%s", err, strings.Join(lines, "\n"))
	}
	return nil
}

func init() {
	register(Command{
		Name:    "issue next",
		Usage:   "issue next [--take [N]] [--person] [--json] [--repo OWNER/NAME]",
		Summary: "name the next se issue, a stuck one before a ready one, or say that none is; --take claims it (or issue N): its branch issue-N, pushed from origin/main, or a stuck one's as it stands, checked out, and fires the routine once (fan-out); --person lists the issues waiting on a person",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue next")
			take := &takeFlag{}
			fs.Var(take, "take", "claim the issue: the next one, or --take N")
			person := fs.Bool("person", false, "list the issues waiting on a person")
			// --take N: the number may stand after --take, between or after the other flags.
			for rest := c.Args; ; {
				if err := fs.Parse(rest); err != nil {
					return Reply{}, err
				}
				if fs.NArg() == 0 {
					break
				}
				n, err := strconv.Atoi(strings.TrimPrefix(fs.Arg(0), "#"))
				if !take.set || err != nil || n <= 0 || take.n != 0 {
					return Reply{}, fmt.Errorf("issue next takes one issue number, after --take, not %q", fs.Arg(0))
				}
				take.n, rest = n, fs.Args()[1:]
			}
			c.Args = nil
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			if *person && take.set {
				return Reply{}, fmt.Errorf("issue next takes --person or --take, not both")
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			if *person {
				waiting, err := s.Waiting()
				if err != nil {
					return Reply{}, err
				}
				return waitingReply(*asJSON, waiting)
			}
			if !take.set {
				next, ok, flagged, err := s.Next()
				if err != nil {
					return Reply{}, err
				}
				return issueReply(*asJSON, next, ok, "", "", flagged)
			}
			took, ok, flagged, err := s.Take(c.Workspace, take.n)
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			if ok {
				fanout = fire()
			}
			return issueReply(*asJSON, took, ok, issues.Branch(took.Number), fanout, flagged)
		},
	})
	register(Command{
		Name:    "issue resume",
		Usage:   "issue resume N [--json] [--repo OWNER/NAME]",
		Summary: "for a person: take issue N off se-person and put it back in the queue, its takeover count reset",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue resume")
			if err := fs.Parse(c.Args); err != nil {
				return Reply{}, err
			}
			n := 0
			if fs.NArg() > 0 {
				n, _ = strconv.Atoi(strings.TrimPrefix(fs.Arg(0), "#"))
			}
			if n <= 0 {
				return Reply{}, fmt.Errorf("issue resume takes an issue number")
			}
			c.Args = fs.Args()[1:]
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			i, err := s.Resume(n)
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Number  int  `json:"number"`
					Resumed bool `json:"resumed"`
				}{i.Number, true})
				return Reply{Text: string(data)}, err
			}
			return Reply{Text: fmt.Sprintf("Resumed #%d %s: back in the queue, its takeover count reset.\n%s", i.Number, i.Title, i.URL)}, nil
		},
	})
	register(Command{
		Name:    "issue new",
		Usage:   "issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none [--json] [--repo OWNER/NAME]",
		Summary: "create an se issue, linked as blocked by each issue named (GitHub's native links), and name it",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue new")
			title := fs.String("title", "", "the issue's title")
			body := fs.String("body", "", "the issue's body")
			bodyFile := fs.String("body-file", "", "a file holding the issue's body")
			blockedBy := fs.String("blocked-by", "", "the issues that block it, as N,M, or none")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			given := map[string]bool{}
			fs.Visit(func(f *flag.Flag) { given[f.Name] = true })
			if !given["blocked-by"] {
				return Reply{}, fmt.Errorf("issue new needs --blocked-by: the issues that block it, as N,M, or none")
			}
			blockers, err := issues.ParseBlockedBy(*blockedBy)
			if err != nil {
				return Reply{}, err
			}
			if given["body"] == given["body-file"] {
				return Reply{}, fmt.Errorf("issue new takes one of --body and --body-file")
			}
			if given["body-file"] {
				path := *bodyFile
				if !filepath.IsAbs(path) {
					path = filepath.Join(c.Workspace, path)
				}
				data, err := os.ReadFile(path)
				if err != nil {
					return Reply{}, err
				}
				*body = string(data)
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			made, err := s.Create(*title, *body, blockers)
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Number    int    `json:"number"`
					URL       string `json:"url"`
					BlockedBy []int  `json:"blocked_by"`
				}{made.Number, made.URL, append([]int{}, blockers...)})
				return Reply{Text: string(data)}, err
			}
			text := fmt.Sprintf("Created #%d %s\n%s", made.Number, made.Title, made.URL)
			if len(blockers) > 0 {
				names := make([]string, len(blockers))
				for k, b := range blockers {
					names[k] = "#" + strconv.Itoa(b)
				}
				text += "\nBlocked by " + strings.Join(names, ", ") + "."
			}
			return Reply{Text: text}, nil
		},
	})
	register(Command{
		Name:    "issue land",
		Usage:   "issue land [--json] [--repo OWNER/NAME]",
		Summary: "on an issue-N branch: pass tests/check.sh, push, open its PR against main (Fixes #N), or find it open, and turn on auto-merge (squash)",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue land")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			l, err := s.Land(c.Workspace, check)
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(l)
				return Reply{Text: string(data)}, err
			}
			did := "Pushed issue-%d; its PR #%d is open"
			if l.Created {
				did = "Pushed issue-%d and opened PR #%d"
			}
			text := fmt.Sprintf(did, l.Issue, l.Number)
			if l.Merged {
				text += "; nothing was left to wait for, so it is merged (squash)."
			} else {
				text += ", auto-merge (squash) on."
			}
			return Reply{Text: text + "\n" + l.URL}, nil
		},
	})
}

// takeFlag is --take, alone or as --take=N; a bare --take N is read by the
// command, since a flag that may stand alone cannot take the next word.
type takeFlag struct {
	set bool
	n   int
}

func (t *takeFlag) IsBoolFlag() bool { return true }

func (t *takeFlag) String() string { return "" }

func (t *takeFlag) Set(v string) error {
	t.set = true
	switch v {
	case "true":
		return nil
	case "false":
		t.set = false
		return nil
	}
	n, err := strconv.Atoi(strings.TrimPrefix(v, "#"))
	if err != nil || n <= 0 {
		return fmt.Errorf("--take takes an issue number, not %q", v)
	}
	t.n = n
	return nil
}

// issueFlags is the flag set every issue command takes; src reads the issues of
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
// a take checked out, fanout what its fan-out did, and flagged the issues the
// sweep gave to a person.
func issueReply(asJSON bool, i issues.Issue, ok bool, branch, fanout string, flagged []issues.Status) (Reply, error) {
	if asJSON {
		answer := struct {
			Ready   bool          `json:"ready"`
			Issue   *issues.Issue `json:"issue,omitempty"`
			Branch  string        `json:"branch,omitempty"`
			Fanout  string        `json:"fanout,omitempty"`
			Flagged []int         `json:"flagged,omitempty"`
		}{Ready: ok, Fanout: fanout}
		if ok {
			answer.Issue, answer.Branch = &i, branch
		}
		for _, f := range flagged {
			answer.Flagged = append(answer.Flagged, f.Number)
		}
		data, err := json.Marshal(answer)
		return Reply{Text: string(data)}, err
	}
	var head string
	for _, f := range flagged {
		head += fmt.Sprintf("Gave #%d %s to a person: stuck a second time.\n", f.Number, f.Title)
	}
	if !ok {
		return Reply{Text: head + "No se issue is ready."}, nil
	}
	if branch != "" {
		head += fmt.Sprintf("Took #%d %s, on branch %s.\n%s", i.Number, i.Title, branch, i.URL)
	} else {
		head += fmt.Sprintf("#%d %s\n%s", i.Number, i.Title, i.URL)
	}
	if fanout != "" {
		head += "\n" + fanout
	}
	return Reply{Text: strings.TrimRight(head+"\n\n"+i.Body, "\n")}, nil
}

// waitingReply lists the issues waiting on a person.
func waitingReply(asJSON bool, waiting []issues.Waiting) (Reply, error) {
	if asJSON {
		data, err := json.Marshal(waiting)
		return Reply{Text: string(data)}, err
	}
	if len(waiting) == 0 {
		return Reply{Text: "No se issue waits on a person."}, nil
	}
	var b strings.Builder
	for k, w := range waiting {
		if k > 0 {
			b.WriteString("\n\n")
		}
		fmt.Fprintf(&b, "#%d %s\n%s\nBlocks %d open issue(s).\n%s", w.Number, w.Title, w.URL, w.Blocks, w.Reason)
	}
	return Reply{Text: b.String()}, nil
}
