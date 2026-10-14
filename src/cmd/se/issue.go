package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/issues"
)

// fire is the fan-out after a claim, and after the creation of a ready issue:
// it fires the routine named in the environment once, on the call's network,
// and answers a line saying what happened.
func (c *Call) fire() string { return issues.Fire(c.Getenv, c.Net) }

// fanOut fires where the fleet needs another box: after a take (taking set)
// or the creation of a ready issue, it counts the alive boxes on s and fires
// only where none is alive or every one runs its cap. With fan-out off it
// reads nothing.
func (c *Call) fanOut(s issues.Source, taking bool) string {
	if c.Getenv(issues.FireURLVar) == "" || c.Getenv(issues.FireTokenVar) == "" {
		return c.fire()
	}
	return s.FanOut(c.fire, taking)
}

// sessionID names the session se runs in, which land records as the leaf's
// worker and review tells apart from them.
func (c *Call) sessionID() string { return c.Getenv(issues.SessionVar) }

// check is the real World's Check: sh ./tests/check.sh, with the last 40
// lines of its output when it fails.
func check(procs proc.Procs, dir string) error {
	out, err := proc.Combined(procs, proc.Cmd{Name: "sh", Args: []string{"./tests/check.sh"}, Dir: dir})
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
		Name:    "issue pull",
		Usage:   "issue pull [--in ROOT] [--take [N]] [--worktree] [--person] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "show the next se issue, stuck work first; --take claims it",
		Details: "pull the next ready se issue at the top, stuck work before new work: without --take it only shows it (number, title, link and body), or says that none is ready, and takes nothing. --take claims it (or issue N): its branch issue-N, pushed from origin/main and checked out. Plain --take first starts and takes an unattended overhaul where 5 retros have closed since the last overhaul closed and none is open, else an unattended retro where 10 se issues have closed since the last retro closed and none is open (the plain form reports both counts); then it takes over a claimed issue whose PR conflicts with main: its branch is checked out as it stands, to merge main into. A claimed leaf nothing was pushed to for longer than the 3-hour lease is stuck: it is taken over before new work, its branch checked out as it stands. A claim stuck a second time, or conflicting after a takeover, goes to a person on the way. A claim records the box's session on the issue, and fires the routine once only where the fleet needs another box: every alive box runs its cap of sub-agents (fleet.box/config/parallel, 4) and another issue is ready (fan-out). --worktree is the box's take: it checks nothing out, names the command that makes the issue's worktree for its sub-agent, and is refused while the box runs its cap. --in ROOT names the ready leaves inside ROOT's tree, and --take claims one for a worktree. --person lists the issues waiting on a person.",
		Session: true,
		Button:  true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue pull")
			take := &takeFlag{}
			fs.Var(take, "take", "claim the next ready issue, or issue N as --take N")
			in := fs.Int("in", 0, "look inside the tree of issue `ROOT` for its ready leaves")
			person := fs.Bool("person", false, "list the issues waiting on a person")
			worktree := fs.Bool("worktree", false, "with --take: claim for a sub-agent's worktree, checking nothing out")
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
					return Reply{}, fmt.Errorf("issue pull takes one issue number, after --take, not %q", fs.Arg(0))
				}
				take.n, rest = n, fs.Args()[1:]
			}
			c.Args = nil
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			if *person && (take.set || *in != 0) {
				return Reply{}, fmt.Errorf("issue pull takes --person alone, without --take or --in")
			}
			if *worktree && (!take.set || *in != 0) {
				return Reply{}, fmt.Errorf("issue pull takes --worktree with --take at the top, without --in: --in always takes for a worktree")
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
				var cads []issues.Cadence
				for _, read := range []func() (issues.Cadence, error){s.Cadence, s.OverhaulCadence} {
					cad, err := read()
					if err != nil {
						return Reply{}, err
					}
					cads = append(cads, cad)
				}
				r, err := issueReply(*asJSON, next, ok, "", "", "", cads...)
				return sweptReply(r, err, *asJSON, flagged)
			}
			// An overhaul, then a retro, the cadence has made due comes
			// before all other work.
			var took issues.Issue
			var ok bool
			var started []issues.Cadence
			s.Worktrees = *worktree
			if take.n == 0 {
				var due issues.Cadence
				if took, ok, due, err = s.TakeDue(c.Workspace); err != nil {
					return Reply{}, err
				}
				if ok {
					started = append(started, due)
				}
			}
			if !ok {
				if took, ok, err = s.Take(c.Workspace, take.n); issues.IsFull(err) {
					return fullReply(*asJSON, err, flagged)
				} else if err != nil {
					return Reply{}, err
				}
			}
			fanout, wt := "", ""
			if ok {
				fanout = c.fanOut(s, true)
				if *worktree && !took.Parent {
					wt = issues.Worktree(c.Workspace, took.Number)
				}
				// What waits for it, so the box can tell which of them need
				// what it may leave over.
				if took.Blocks, err = s.Dependents(took.Number); err != nil {
					return Reply{}, err
				}
			}
			r, err := issueReply(*asJSON, took, ok, issues.Branch(took.Number), wt, fanout, started...)
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
		Name:    "issue tree",
		Usage:   "issue tree [ROOT] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "list the se trees and how many of their sub-issues are closed",
		Details: "list every se issue with sub-issues, open or closed, open first: its number, state, how many of its sub-issues are closed, its labels and its title. With ROOT, list ROOT and every issue below it, open or closed, each indented under its parent.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue tree")
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
			root := 0
			if len(words) > 0 {
				root, _ = strconv.Atoi(strings.TrimPrefix(words[0], "#"))
				if len(words) > 1 || root <= 0 {
					return Reply{}, fmt.Errorf("issue tree takes at most one issue number, not %q", strings.Join(words, " "))
				}
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			if err := s.CloseParents(); err != nil {
				return Reply{}, err
			}
			var nodes []issues.Node
			if root > 0 {
				nodes, err = s.TreeOf(root)
			} else {
				nodes, err = s.Trees()
			}
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(nodes)
				return Reply{Text: string(data)}, err
			}
			if len(nodes) == 0 {
				return Reply{Text: "No se issue has sub-issues."}, nil
			}
			lines := make([]string, len(nodes))
			for k, n := range nodes {
				lines[k] = n.Line()
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
	register(Command{
		Name:    "issue new",
		Usage:   "issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none [--parent N] [--blocks N,M] [--review] [--final] [--person] [--allow-duplicate] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "create an se issue, with its blockers and its parent",
		Details: "create an se issue, linked as blocked by each issue --blocked-by names (GitHub's native links), as a sub-issue of --parent, and name it. --blocks links each issue it names as blocked by the new one: those dependents of a box's issue that need what is left of it. --review labels it se-review; --final labels it se-final, its last attempt before a person. --person makes it an issue for a person: labelled se-person and assigned to the owner, it waits for them, and its body opens with what they decide. It refuses a title an open se issue under the same --parent (or at the top) has already, naming it, unless --allow-duplicate is given. A ready issue, one nothing open blocks, fires the routine once.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue new")
			title := fs.String("title", "", "the issue's title `T`")
			body := fs.String("body", "", "the issue's body `B`")
			bodyFile := fs.String("body-file", "", "a file `PATH` holding the issue's body")
			blockedBy := fs.String("blocked-by", "", "the issues that block it, as `N,M`, or none")
			parent := fs.Int("parent", 0, "the issue `N` it is a sub-issue of")
			blocks := fs.String("blocks", "", "the issues it blocks, as `N,M`: those that need it")
			review := fs.Bool("review", false, "label it se-review: it is reviewed once its sub-issues have closed")
			final := fs.Bool("final", false, "label it se-final: if it fails, it goes to a person")
			person := fs.Bool("person", false, "make it an issue for a person: label it se-person and assign it to the owner")
			allowDuplicate := fs.Bool("allow-duplicate", false, "create it although an open se issue under the same parent has its title")
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
			var dependents []int
			if given["blocks"] {
				if dependents, err = issues.ParseBlockedBy(*blocks); err != nil || len(dependents) == 0 {
					return Reply{}, fmt.Errorf("--blocks takes issue numbers, like 5,8, not %q", *blocks)
				}
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
			if *allowDuplicate {
				if err := s.CloseParents(); err != nil {
					return Reply{}, err
				}
			} else if dup, err := s.Duplicate(*title, *parent); err != nil {
				return Reply{}, err
			} else if dup > 0 {
				where := "at the top"
				if *parent > 0 {
					where = fmt.Sprintf("a sub-issue of #%d", *parent)
				}
				return Reply{}, fmt.Errorf("#%d is an open se issue titled %q, %s, already; --allow-duplicate creates another", dup, strings.TrimSpace(*title), where)
			}
			var labels []string
			if *review {
				labels = append(labels, issues.ReviewLabel)
			}
			if *final {
				labels = append(labels, issues.FinalLabel)
			}
			if err := s.Exist(dependents); err != nil {
				return Reply{}, err
			}
			var made issues.Issue
			ready := false
			if *person {
				if len(labels) > 0 {
					return Reply{}, fmt.Errorf("--person takes neither --review nor --final: an issue for a person is no box's work")
				}
				made, err = s.ForPerson(*title, *body, *parent, blockers)
			} else {
				made, ready, err = s.Create(*title, *body, *parent, blockers, labels...)
			}
			if err != nil {
				return Reply{}, err
			}
			if err := s.Blocking(made, dependents); err != nil {
				return Reply{}, err
			}
			fanout := ""
			if ready {
				fanout = c.fanOut(s, false)
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Number    int    `json:"number"`
					URL       string `json:"url"`
					BlockedBy []int  `json:"blocked_by"`
					Parent    int    `json:"parent,omitempty"`
					Blocks    []int  `json:"blocks,omitempty"`
					Review    bool   `json:"review,omitempty"`
					Final     bool   `json:"final,omitempty"`
					Person    bool   `json:"person,omitempty"`
					Fanout    string `json:"fanout,omitempty"`
				}{made.Number, made.URL, append([]int{}, blockers...), *parent, dependents, *review, *final, *person, fanout})
				return Reply{Text: string(data)}, err
			}
			text := fmt.Sprintf("Created #%d %s\n%s", made.Number, made.Title, made.URL)
			if *parent > 0 {
				text += fmt.Sprintf("\nA sub-issue of #%d.", *parent)
			}
			if *review {
				text += "\nLabelled " + issues.ReviewLabel + ": it is reviewed once its sub-issues have closed."
			}
			if len(dependents) > 0 {
				text += "\nIt blocks " + numbers(dependents) + "."
			}
			if *person {
				text += "\nFor a person: labelled " + issues.PersonLabel + " and assigned to the owner."
			}
			if *final {
				text += "\nLabelled " + issues.FinalLabel + ": if it fails, it goes to a person."
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
		Details: "on an issue-N branch of a leaf: refuse unless FILE answers every question in spec/landing.yaml (YAML keyed by their keys, none empty, none unknown; a relative FILE is read from the workspace), pass tests/check.sh, push, post the answers on the issue (or update the ones posted before), open its PR against main (Fixes #N, and the battery's profile), or find it open with its profile brought up to date, and turn on auto-merge (squash).",
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
			l, err := s.Land(c.Workspace, c.sessionID(), qs, answers, func(dir string) error { return c.Check(c.Proc, dir) })
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
		Usage:   "issue review pass|fail N --report PATH [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "pass or fail a gate whose sub-issues have closed, by its report",
		Details: "review N, an se-review parent whose sub-issues have closed, as an agent that worked none of its tree, with the report in the JSON file PATH (spec/review.md). It refuses a pass where a requirement lacks evidence, and a report without its checked-and-clean list. Every finding becomes an se-final issue: a blocking one a sub-issue of N, a non-blocking one in the queue (five at most). pass posts the report and closes N; fail posts it, and N waits for its fixes. A re-review that finds an earlier blocker's problem again sends N to a person.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue review")
			report := fs.String("report", "", "the review's report, a JSON file at `PATH`")
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
			if *report == "" {
				return Reply{}, fmt.Errorf("issue review needs --report: the review's report, a JSON file (spec/review.md)")
			}
			path := *report
			if !filepath.IsAbs(path) {
				path = filepath.Join(c.Workspace, path)
			}
			data, err := c.Disk.ReadFile(path)
			if err != nil {
				return Reply{}, err
			}
			var rep issues.Report
			dec := json.NewDecoder(strings.NewReader(string(data)))
			dec.DisallowUnknownFields()
			if err := dec.Decode(&rep); err != nil {
				return Reply{}, fmt.Errorf("the report %s is not a review report (spec/review.md): %v", *report, err)
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			reviewer := issues.Worker{Session: c.sessionID(), Workspace: c.Workspace}
			r, err := s.Review(n, reviewer, words[0] == "pass", rep)
			if err != nil {
				return Reply{}, err
			}
			// A filed finding is a ready issue in the queue: it fires once.
			fanout := ""
			if len(r.Filed) > 0 {
				fanout = c.fire()
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					issues.Reviewed
					Fanout string `json:"fanout,omitempty"`
				}{r, fanout})
				return Reply{Text: string(data)}, err
			}
			var lines []string
			switch {
			case r.Person:
				lines = append(lines, fmt.Sprintf("#%d's re-review found an earlier blocker's problem again: the report is on it, and it waits on a person.", n))
			case r.Passed:
				lines = append(lines, fmt.Sprintf("Passed #%d: the report is on it, and it is closed.", n))
			default:
				lines = append(lines, fmt.Sprintf("Failed #%d: the report is on it, and its blocking findings are sub-issues of it:", n))
			}
			for _, f := range r.Fixes {
				lines = append(lines, fmt.Sprintf("#%d %s\n%s", f.Number, f.Title, f.URL))
			}
			if len(r.Filed) > 0 {
				lines = append(lines, "Filed, not blocking:")
			}
			for _, f := range r.Filed {
				lines = append(lines, fmt.Sprintf("#%d %s\n%s", f.Number, f.Title, f.URL))
			}
			if r.Unfiled > 0 {
				lines = append(lines, fmt.Sprintf("%d more non-blocking finding(s) counted, not filed.", r.Unfiled))
			}
			if fanout != "" {
				lines = append(lines, fanout)
			}
			return Reply{Text: strings.Join(lines, "\n")}, nil
		},
	})
	register(Command{
		Name:    "review brief",
		Usage:   "review brief N [--claims] [--json] [--repo OWNER/NAME]",
		Group:   "Reviews",
		Summary: "everything a reviewer of gate N starts from",
		Details: "print the brief of gate N's review: its question, the text of every issue in its tree, main's head as the pinned commit, the CI there and spec/principles.md; for a re-review, the earlier blockers and the diff since. The workers' PR descriptions and comments are withheld; --claims adds them, once the findings are verified, as claims to check.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "review brief")
			claims := fs.Bool("claims", false, "add the workers' accounts, as claims to check, once the findings are verified")
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
				return Reply{}, fmt.Errorf("review brief takes one issue number, not %q", strings.Join(words, " "))
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			b, err := s.Brief(n, *claims)
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(b)
				return Reply{Text: string(data)}, err
			}
			return Reply{Text: strings.TrimRight(b.Text(), "\n")}, nil
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
	repo := fs.String("repo", "", "the repository as `OWNER/NAME` (default: the workspace's origin)")
	return fs, func() (issues.Source, error) {
		if *repo == "" {
			r, err := issues.Repo(c.Proc, c.Workspace)
			if err != nil {
				return issues.Source{}, err
			}
			*repo = r
		}
		// stdout is the answer; what se waits on goes beside it, as it waits.
		waits := func(note string) { fmt.Fprintln(os.Stderr, "se:", note) }
		return issues.Source{Repo: *repo, GitHub: c.GitHub, Clock: c.Clock, Disk: c.Disk, Proc: c.Proc, Waits: waits, Box: c.sessionID()}, nil
	}, asJSON
}

// issueReply shows the issue, or that there was none; branch names the branch
// a take claimed, worktree the command that makes its worktree where the take
// checked nothing out, fanout what its fan-out did, and cads where the retro
// and overhaul cadences stand. A take passes the one cadence that started its
// issue, if any.
func issueReply(asJSON bool, i issues.Issue, ok bool, branch, worktree, fanout string, cads ...issues.Cadence) (Reply, error) {
	if asJSON {
		answer := struct {
			Ready     bool            `json:"ready"`
			Issue     *issues.Issue   `json:"issue,omitempty"`
			Branch    string          `json:"branch,omitempty"`
			Worktree  string          `json:"worktree,omitempty"`
			Fanout    string          `json:"fanout,omitempty"`
			Retros    *issues.Cadence `json:"retros,omitempty"`
			Overhauls *issues.Cadence `json:"overhauls,omitempty"`
		}{Ready: ok, Fanout: fanout}
		for k := range cads {
			if cads[k].Kind == "overhaul" {
				answer.Overhauls = &cads[k]
			} else {
				answer.Retros = &cads[k]
			}
		}
		if ok {
			answer.Issue, answer.Branch, answer.Worktree = &i, branch, worktree
		}
		data, err := json.Marshal(answer)
		return Reply{Text: string(data)}, err
	}
	tail := ""
	for _, cad := range cads {
		tail += "\n\n" + cad.Line()
	}
	if !ok {
		return Reply{Text: "No se issue is ready." + tail}, nil
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
	case branch != "" && len(cads) > 0:
		cad := cads[0]
		head = fmt.Sprintf("Started the unattended %s #%d %s, as %d %s closed since the last one (the cadence is %d), and took it, on branch %s.\n%s",
			cad.Kind, i.Number, i.Title, cad.Closed, cad.Counts(), cad.Every, branch, i.URL)
		tail = ""
	case branch != "":
		head = fmt.Sprintf("Took #%d %s, on branch %s.\n%s", i.Number, i.Title, branch, i.URL)
	case t != nil:
		head += fmt.Sprintf("\nIt is stuck: a take takes it over and continues its branch %s.", issues.Branch(i.Number))
	}
	if worktree != "" {
		head += "\n\nIts sub-agent works in its own worktree:\n" + worktree
	}
	if branch != "" && len(i.Blocks) > 0 {
		head += fmt.Sprintf("\nIt blocks %s. What you leave over, filed with se issue new, names in --blocks those of them that need it.", numbers(i.Blocks))
	}
	if fanout != "" {
		head += "\n" + fanout
	}
	if i.Retro {
		head += fmt.Sprintf("\n\n#%d is a retro (%s): follow the retro skill, src/plugin/skills/retro/SKILL.md, from se retro collect %d", i.Number, issues.RetroLabel, i.Number)
	}
	if i.Overhaul {
		head += fmt.Sprintf("\n\n#%d is an overhaul (%s): follow the overhaul skill, src/plugin/skills/overhaul/SKILL.md, from se overhaul read %d", i.Number, issues.OverhaulLabel, i.Number)
	}
	if i.Parent {
		head += fmt.Sprintf("\n\n#%d is a parent: it holds no work. Coordinate its tree: se issue pull --in %d --take", i.Number, i.Number)
	}
	return Reply{Text: strings.TrimRight(head+"\n\n"+i.Body, "\n") + tail}, nil
}

// inReply answers issue pull --in: what is ready inside root's tree, or, with
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
	if issues.IsFull(err) {
		return fullReply(asJSON, err, nil)
	}
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

// fullReply answers a box's take refused because it runs its cap of
// sub-agents (with --json: {"ready":false,"full":true}).
func fullReply(asJSON bool, err error, flagged []string) (Reply, error) {
	if asJSON {
		data, jerr := json.Marshal(map[string]any{"ready": false, "full": true, "why": err.Error()})
		return sweptReply(Reply{Text: string(data)}, jerr, true, flagged)
	}
	return sweptReply(Reply{Text: "No take: " + err.Error() + "."}, nil, false, flagged)
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
// reviewer's fresh worktree and the model its reviewer runs (spec/models.yaml;
// empty: the box's own).
type reviewAt struct {
	issues.Issue
	Worktree string `json:"worktree"`
	Model    string `json:"model,omitempty"`
}

func reviews(c *Call, tr issues.Tree) []reviewAt {
	out := []reviewAt{}
	for _, i := range tr.Review {
		out = append(out, reviewAt{i, tr.ReviewWorktree(c.Workspace, i.Number), issues.ReviewerModel(c.Disk, c.Workspace)})
	}
	return out
}

// reviewText names, after a take, the parents ready for review and where
// their reviewers work.
func reviewText(c *Call, tr issues.Tree) string {
	text := ""
	for _, r := range reviews(c, tr) {
		text += fmt.Sprintf("\n\nReady for review: #%d %s\n%s\nA reviewer that worked none of its tree works in a fresh worktree:\n%s", r.Number, r.Title, r.URL, r.Worktree)
		if r.Model != "" {
			text += "\nIts reviewer runs the model " + r.Model + " (" + issues.ModelsPath + ")."
		}
	}
	return text
}

// sweptReply adds to a reply of issue pull the issues its sweep gave to a
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
