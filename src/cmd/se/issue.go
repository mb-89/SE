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

	"github.com/mb-89/SE/src/internal/issues"
)

// gh is how the issue commands reach GitHub; tests put recorded answers here.
var gh issues.GH = issues.Gh

// fire is the fan-out after a claim, and after the creation of a ready issue:
// it fires the routine once and answers a line saying what happened. Tests put a fake here.
var fire = issues.FireFromEnv

// sessionID names the session se runs in, which land records as the leaf's
// worker and review tells apart from them. Tests put a fixed one here.
var sessionID = func() string { return os.Getenv(issues.SessionVar) }

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
		Usage:   "issue next [--in ROOT] [--take [N]] [--person] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "name the next se issue, stuck work first; --take claims it",
		Details: "name the next ready se issue at the top, stuck work before new work, or say that none is ready. --take claims it (or issue N): its branch issue-N, pushed from origin/main and checked out. Plain --take first takes over a claimed issue whose PR conflicts with main: its branch is checked out as it stands, to merge main into. A claimed leaf nothing was pushed to for longer than the 3-hour lease is stuck: it is taken over before new work, its branch checked out as it stands. A claim stuck a second time, or conflicting after a takeover, goes to a person on the way. A claim fires the routine once (fan-out). --in ROOT names the ready leaves inside ROOT's tree, and --take claims one for a worktree. --person lists the issues waiting on a person.",
		Session: true,
		Button:  true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue next")
			take := &takeFlag{}
			fs.Var(take, "take", "claim the next ready issue, or issue N as --take N")
			in := fs.Int("in", 0, "look inside the tree of issue `ROOT` for its ready leaves")
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
			if *person && (take.set || *in != 0) {
				return Reply{}, fmt.Errorf("issue next takes --person alone, without --take or --in")
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			var flagged []string
			s.Flagged = func(i issues.Issue, reason string) {
				flagged = append(flagged, fmt.Sprintf("Gave #%d %s to a person: %s", i.Number, i.Title, reason))
			}
			if *person {
				waiting, err := s.Waiting()
				if err != nil {
					return Reply{}, err
				}
				return waitingReply(*asJSON, waiting, flagged)
			}
			if *in < 0 {
				return Reply{}, fmt.Errorf("--in takes an issue number, not %d", *in)
			}
			if *in > 0 {
				r, err := inReply(c, s, *asJSON, *in, take)
				return sweptReply(r, err, *asJSON, flagged)
			}
			if !take.set {
				next, ok, err := s.Next()
				if err != nil {
					return Reply{}, err
				}
				r, err := issueReply(*asJSON, next, ok, "", "")
				return sweptReply(r, err, *asJSON, flagged)
			}
			took, ok, err := s.Take(c.Workspace, take.n)
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			if ok {
				fanout = fire()
			}
			r, err := issueReply(*asJSON, took, ok, issues.Branch(took.Number), fanout)
			return sweptReply(r, err, *asJSON, flagged)
		},
	})
	register(Command{
		Name:    "issue resume",
		Usage:   "issue resume N [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "for a person: put issue N back in the queue",
		Details: "for a person: take issue N off se-person and put it back in the queue, its takeover count reset.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue resume")
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
				return Reply{}, fmt.Errorf("issue resume takes one issue number, not %q", strings.Join(words, " "))
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			if err := s.CloseParents(); err != nil {
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
		Usage:   "issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none [--parent N] [--review] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "create an se issue, with its blockers and its parent",
		Details: "create an se issue, linked as blocked by each issue --blocked-by names (GitHub's native links), as a sub-issue of --parent, and name it. --review labels it se-review. A ready issue, one nothing open blocks, fires the routine once.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue new")
			title := fs.String("title", "", "the issue's title `T`")
			body := fs.String("body", "", "the issue's body `B`")
			bodyFile := fs.String("body-file", "", "a file `PATH` holding the issue's body")
			blockedBy := fs.String("blocked-by", "", "the issues that block it, as `N,M`, or none")
			parent := fs.Int("parent", 0, "the issue `N` it is a sub-issue of")
			review := fs.Bool("review", false, "label it se-review: it is reviewed once its sub-issues have closed")
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
			if *parent < 0 {
				return Reply{}, fmt.Errorf("--parent takes an issue number, not %d", *parent)
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
			if err := s.CloseParents(); err != nil {
				return Reply{}, err
			}
			made, ready, err := s.Create(*title, *body, *parent, blockers, *review)
			if err != nil {
				return Reply{}, err
			}
			fanout := ""
			if ready {
				fanout = fire()
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Number    int    `json:"number"`
					URL       string `json:"url"`
					BlockedBy []int  `json:"blocked_by"`
					Parent    int    `json:"parent,omitempty"`
					Review    bool   `json:"review,omitempty"`
					Fanout    string `json:"fanout,omitempty"`
				}{made.Number, made.URL, append([]int{}, blockers...), *parent, *review, fanout})
				return Reply{Text: string(data)}, err
			}
			text := fmt.Sprintf("Created #%d %s\n%s", made.Number, made.Title, made.URL)
			if *parent > 0 {
				text += fmt.Sprintf("\nA sub-issue of #%d.", *parent)
			}
			if *review {
				text += "\nLabelled " + issues.ReviewLabel + ": it is reviewed once its sub-issues have closed."
			}
			if len(blockers) > 0 {
				names := make([]string, len(blockers))
				for k, b := range blockers {
					names[k] = "#" + strconv.Itoa(b)
				}
				text += "\nBlocked by " + strings.Join(names, ", ") + "."
			}
			if fanout != "" {
				text += "\n" + fanout
			}
			return Reply{Text: text}, nil
		},
	})
	register(Command{
		Name:    "issue land",
		Usage:   "issue land --answers FILE [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "check, push and open the PR of an issue-N branch, auto-merge on",
		Details: "on an issue-N branch of a leaf: refuse unless FILE answers every question in spec/landing.yaml (YAML keyed by their keys, none empty, none unknown; a relative FILE is read from the workspace), pass tests/check.sh, push, post the answers on the issue (or update the ones posted before), open its PR against main (Fixes #N), or find it open, and turn on auto-merge (squash).",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue land")
			file := fs.String("answers", "", "the landing answers, a YAML `FILE` keyed as spec/landing.yaml")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			if *file == "" {
				return Reply{}, fmt.Errorf("issue land takes --answers FILE: an answer to every question in %s", issues.QuestionsFile)
			}
			if !filepath.IsAbs(*file) {
				*file = filepath.Join(c.Workspace, *file)
			}
			qs, err := issues.Questions(c.Workspace)
			if err != nil {
				return Reply{}, err
			}
			answers, err := issues.ReadAnswers(*file)
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
			l, err := s.Land(c.Workspace, sessionID(), qs, answers, check)
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

func init() {
	register(Command{
		Name:    "issue review",
		Usage:   "issue review pass|fail N --why TEXT [--fix TITLE]... [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "pass or fail a parent whose sub-issues have closed",
		Details: "review N, an se-review parent whose sub-issues have closed, as an agent that worked none of its tree. pass posts the verdict and closes it; fail posts the findings and creates a fix leaf under it per --fix.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue review")
			why := fs.String("why", "", "the verdict, or the findings, as `TEXT`")
			var fixes fixList
			fs.Var(&fixes, "fix", "the `TITLE` of a fix leaf a fail creates (repeat it for each)")
			// The words pass|fail and N may stand before, between or after the flags.
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
			if len(words) != 2 || (words[0] != "pass" && words[0] != "fail") {
				return Reply{}, fmt.Errorf("issue review takes pass or fail, then an issue number, not %q", strings.Join(words, " "))
			}
			n, err := strconv.Atoi(strings.TrimPrefix(words[1], "#"))
			if err != nil || n <= 0 {
				return Reply{}, fmt.Errorf("issue review takes an issue number, not %q", words[1])
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			reviewer := issues.Worker{Session: sessionID(), Workspace: c.Workspace}
			r, err := s.Review(n, reviewer, words[0] == "pass", *why, fixes)
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(r)
				return Reply{Text: string(data)}, err
			}
			if r.Passed {
				return Reply{Text: fmt.Sprintf("Passed #%d: the verdict is on it, and it is closed.", n)}, nil
			}
			lines := []string{fmt.Sprintf("Failed #%d: the findings are on it, and its fixes are sub-issues of it:", n)}
			for _, f := range r.Fixes {
				lines = append(lines, fmt.Sprintf("#%d %s\n%s", f.Number, f.Title, f.URL))
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
}

// fixList is --fix, which may repeat.
type fixList []string

func (f *fixList) String() string { return strings.Join(*f, ", ") }

func (f *fixList) Set(v string) error {
	*f = append(*f, v)
	return nil
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
	repo := fs.String("repo", "", "the repository as `OWNER/NAME` (default: the workspace's origin)")
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
// a take checked out, and fanout what its fan-out did.
func issueReply(asJSON bool, i issues.Issue, ok bool, branch, fanout string) (Reply, error) {
	if asJSON {
		answer := struct {
			Ready  bool          `json:"ready"`
			Issue  *issues.Issue `json:"issue,omitempty"`
			Branch string        `json:"branch,omitempty"`
			Fanout string        `json:"fanout,omitempty"`
		}{Ready: ok, Fanout: fanout}
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
	t := i.Takeover
	switch {
	case branch != "" && t != nil && t.PR != 0 && t.Stale == "":
		head = fmt.Sprintf("Took over #%d %s, on branch %s: its PR #%d conflicts with main (takeover %d).\n%s\n%s\nMerge origin/main into %s (never rebase, never force-push), resolve the conflict, and land it again with se issue land.",
			i.Number, i.Title, branch, t.PR, t.Count, i.URL, t.URL, branch)
	case branch != "" && t != nil:
		head = fmt.Sprintf("Took over #%d %s, on branch %s as it stands: it was stuck, %s (takeover %d).\n%s", i.Number, i.Title, branch, t.Stale, t.Count, i.URL)
		if t.URL != "" {
			head += "\n" + t.URL
		}
		head += fmt.Sprintf("\nMerge origin/main into %s (never rebase, never force-push), continue the branch and its PR, make it green, and land it again with se issue land.", branch)
	case branch != "":
		head = fmt.Sprintf("Took #%d %s, on branch %s.\n%s", i.Number, i.Title, branch, i.URL)
	case t != nil:
		head += fmt.Sprintf("\nIt is stuck: a take takes it over and continues its branch %s.", issues.Branch(i.Number))
	}
	if fanout != "" {
		head += "\n" + fanout
	}
	if i.Retro {
		head += fmt.Sprintf("\n\n#%d is a retro (%s): follow the retro skill, src/plugin/skills/retro/SKILL.md, from se retro collect %d", i.Number, issues.RetroLabel, i.Number)
	}
	if i.Parent {
		head += fmt.Sprintf("\n\n#%d is a parent: it holds no work. Coordinate its tree: se issue next --in %d --take", i.Number, i.Number)
	}
	return Reply{Text: strings.TrimRight(head+"\n\n"+i.Body, "\n")}, nil
}

// inReply answers issue next --in: what is ready inside root's tree, or, with
// --take, the leaf claimed and the worktree command that checks it out.
func inReply(c *Call, s issues.Source, asJSON bool, root int, take *takeFlag) (Reply, error) {
	if !take.set {
		tr, err := s.In(root)
		if err != nil {
			return Reply{}, err
		}
		if asJSON {
			data, err := json.Marshal(tr)
			return Reply{Text: string(data)}, err
		}
		return Reply{Text: treeText(tr)}, nil
	}
	took, ok, tr, err := s.TakeIn(c.Workspace, root, take.n)
	if err != nil {
		return Reply{}, err
	}
	worktree := ""
	if ok {
		worktree = issues.Worktree(c.Workspace, took.Number)
	}
	if asJSON {
		answer := struct {
			Ready    bool          `json:"ready"`
			Closed   bool          `json:"closed"`
			Issue    *issues.Issue `json:"issue,omitempty"`
			Branch   string        `json:"branch,omitempty"`
			Worktree string        `json:"worktree,omitempty"`
			Review   []reviewAt    `json:"review"`
		}{Ready: ok, Closed: tr.Closed, Review: reviews(c, tr)}
		if ok {
			answer.Issue, answer.Branch, answer.Worktree = &took, issues.Branch(took.Number), worktree
		}
		data, err := json.Marshal(answer)
		return Reply{Text: string(data)}, err
	}
	if !ok {
		work := tr
		work.Review = nil
		return Reply{Text: treeText(work) + reviewText(c, tr)}, nil
	}
	did := "Took #%d %s, on branch %s.\n%s\n\nWork in its own worktree:\n%s"
	if took.Takeover != nil {
		did = "Took over #%d %s, on branch %s as it stands: it was stuck.\n%s\n\nContinue the branch and its PR in its own worktree:\n%s"
	}
	text := fmt.Sprintf(did, took.Number, took.Title, issues.Branch(took.Number), took.URL, worktree) + reviewText(c, tr)
	return Reply{Text: strings.TrimRight(text+"\n\n"+took.Body, "\n")}, nil
}

// treeText says where a tree stands.
func treeText(tr issues.Tree) string {
	if tr.Closed {
		return fmt.Sprintf("#%d is closed.", tr.Root)
	}
	if tr.Why != "" {
		return fmt.Sprintf("Nothing inside #%d is ready: %s.", tr.Root, tr.Why)
	}
	if len(tr.Ready)+len(tr.Review) == 0 {
		return fmt.Sprintf("Nothing inside #%d is ready.", tr.Root)
	}
	var lines []string
	for _, i := range tr.Ready {
		what := "Ready"
		if i.Takeover != nil {
			what = "Stuck, to take over"
		}
		lines = append(lines, fmt.Sprintf("%s: #%d %s\n%s", what, i.Number, i.Title, i.URL))
	}
	for _, i := range tr.Review {
		lines = append(lines, fmt.Sprintf("Ready for review: #%d %s\n%s", i.Number, i.Title, i.URL))
	}
	return strings.Join(lines, "\n")
}

// reviewAt is a parent ready for review, with the command that makes its
// reviewer's fresh worktree.
type reviewAt struct {
	issues.Issue
	Worktree string `json:"worktree"`
}

func reviews(c *Call, tr issues.Tree) []reviewAt {
	out := []reviewAt{}
	for _, i := range tr.Review {
		out = append(out, reviewAt{i, tr.ReviewWorktree(c.Workspace, i.Number)})
	}
	return out
}

// reviewText names, after a take, the parents ready for review and where
// their reviewers work.
func reviewText(c *Call, tr issues.Tree) string {
	text := ""
	for _, r := range reviews(c, tr) {
		text += fmt.Sprintf("\n\nReady for review: #%d %s\n%s\nA reviewer that worked none of its tree works in a fresh worktree:\n%s", r.Number, r.Title, r.URL, r.Worktree)
	}
	return text
}

// sweptReply adds to a reply of issue next the issues its sweep gave to a
// person: lines before the text, or with --json the field "flagged".
func sweptReply(r Reply, err error, asJSON bool, flagged []string) (Reply, error) {
	if err != nil || len(flagged) == 0 {
		return r, err
	}
	if !asJSON {
		r.Text = strings.Join(flagged, "\n") + "\n\n" + r.Text
		return r, nil
	}
	var answer map[string]any
	if err := json.Unmarshal([]byte(r.Text), &answer); err != nil {
		return Reply{}, err
	}
	answer["flagged"] = flagged
	data, err := json.Marshal(answer)
	return Reply{Text: string(data)}, err
}

// waitingReply lists the issues waiting on a person.
func waitingReply(asJSON bool, waiting []issues.Waiting, flagged []string) (Reply, error) {
	if asJSON {
		data, err := json.Marshal(waiting)
		return Reply{Text: string(data)}, err
	}
	if len(waiting) == 0 {
		return sweptReply(Reply{Text: "No se issue waits on a person."}, nil, false, flagged)
	}
	var b strings.Builder
	for k, w := range waiting {
		if k > 0 {
			b.WriteString("\n\n")
		}
		fmt.Fprintf(&b, "#%d %s\n%s\nBlocks %d open issue(s).\n%s", w.Number, w.Title, w.URL, w.Blocks, w.Reason)
	}
	return sweptReply(Reply{Text: b.String()}, nil, false, flagged)
}
