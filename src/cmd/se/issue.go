package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/guidance"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/issues"
	"github.com/mb-89/SE/src/internal/reuse"
)

// fire is the fan-out after a claim, and after the creation of a ready issue:
// it fires the routine named in the environment once, on the call's network,
// and answers a line saying what happened.
func (c *Call) fire() string { return issues.Fire(c.Getenv, c.Net) }

// shoot is fire, answering also whether the routine refused it for its rate
// limit and when it may fire again.
func (c *Call) shoot() issues.Shot { return issues.Shoot(c.Getenv, c.Net) }

// fanOutOn says whether fan-out is on: both of the routine's variables set.
func (c *Call) fanOutOn() bool {
	return c.Getenv(issues.FireURLVar) != "" && c.Getenv(issues.FireTokenVar) != ""
}

// fanOut fires where the fleet needs another box: after the take of claim,
// or the creation of a ready issue (claim zero), it counts the alive boxes on
// s and fires only where none is alive or every one runs its cap, and keeps a
// fire the routine refused with 429 for the take or fleet check after its
// retry time. With fan-out off it reads nothing.
func (c *Call) fanOut(s issues.Source, claim int) string {
	if !c.fanOutOn() {
		return c.fire()
	}
	return s.FanOut(c.shoot, claim)
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
		Class:   interactive,
		Usage:   "issue pull [--in ROOT] [--take [N]] [--worktree] [--person] [--full] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "show the next se issue, stuck work first; --take claims it",
		Details: fmt.Sprintf("pull the next ready se issue at the top, stuck work before new work; boxes take only manifests, so at the top it offers a manifest (a parent), a retro or an overhaul, never a leaf in no manifest, and a manifest whose leaves are all closed is offered to be landed as one PR. After stuck and conflicted work, it offers the priority manifests first, lowest number first: those labelled se-priority or holding an open leaf so labelled, and an open retro or overhaul; inside a manifest, its se-priority leaves come before the rest. Every --take first reads fleet.box/config/paused (issues/config/paused) in the wiring file on origin/main, and while it is set takes nothing and says the fleet is paused, so the box ends. Without --take it only shows it (number, title, link, why it is at the top, and where the cadences stand; --full adds the body), or says that none is ready, and takes nothing; a press of its /se ui button shows the short form, the cadences in one line. --take claims it (or issue N): its branch issue-N, pushed from origin/main and checked out. Plain --take first starts and takes an unattended overhaul where %d retros (issues/config/overhaul-cadence) have closed since the last overhaul closed and none is open, else an unattended retro where %d se issues (issues/config/retro-cadence), final ones (se-final) not counted, have closed since the last retro closed and none is open (the plain form reports both counts); then it takes over a claimed issue whose PR conflicts with main: its branch is checked out as it stands, to merge main into. A claimed leaf nothing was pushed to for longer than the %s lease (issues/config/lease) is stuck: it is taken over before new work, its branch checked out as it stands. A takeover writes the landing answers the issue's last land posted on it back to <checkout>-landing.yaml beside its checkout (its worktree with --worktree or --in), keeping a file there already, and names it. A claim stuck a second time, or conflicting after a takeover, is taken over again; nothing mints an issue for a person on a box's behalf. A claim records the box's session on the issue, and fires the routine once only where the fleet needs another box: every alive box runs its cap of sub-agents (fleet.box/config/parallel, %d, Parallel) and another issue is ready (fan-out); a fire the routine refuses with 429 is kept on the claim with the retry time it names, nothing fires before that time, and the next take or se fleet check after it fires it. --worktree is the box's take: it checks nothing out, names the command that makes the issue's worktree for its sub-agent, and is refused while the box runs its cap. A take hands over every skill the issue's marked skills line names (se issue new --skills): their full text follows the issue, or, where the guidance instance's inline switch is off, their names and files; the session's log records each by name and hash. A name there that is an agent's role, as retro or overhaul, is no skill: the take's agent holds it, so it is neither handed over nor reported missing. A take names the agent that works the issue, by its kind (the registry in src/internal/issues/kinds.go): se:worker for a leaf, se:coordinator for a parent, which is the box itself, se:retro and se:overhaul; each review names se:reviewer. --in ROOT names the ready leaves inside ROOT's tree, and --take claims one for a worktree. Every --take also refuses where main has moved past the commit se was built from, naming se update: the agents and guidance it hands over come from main. --person lists the issues waiting on a person.", issueConfig().OverhaulCadence, issueConfig().RetroCadence, issueConfig().Lease, issues.Parallel),
		Session: true,
		Button:  true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue pull")
			take := &takeFlag{}
			fs.Var(take, "take", "claim the next ready issue, or issue N as --take N")
			in := fs.Int("in", 0, "look inside the tree of issue `ROOT` for its ready leaves")
			person := fs.Bool("person", false, "list the issues waiting on a person")
			worktree := fs.Bool("worktree", false, "with --take: claim for a sub-agent's worktree, checking nothing out")
			full := fs.Bool("full", false, "without --take: show the issue's body too")
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
			if take.set {
				if err := staleSE(&c.World); err != nil {
					return Reply{}, err
				}
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
			if *in < 0 {
				return Reply{}, fmt.Errorf("--in takes an issue number, not %d", *in)
			}
			// The pause switch on main stops every take, at the top and
			// inside a tree, so the owner stops the fleet with one change.
			if take.set {
				if paused, err := s.Paused(c.Workspace); err != nil {
					return Reply{}, err
				} else if paused {
					return pausedReply(*asJSON)
				}
			}
			if *in > 0 {
				return inReply(c, s, *asJSON, *in, take)
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
				return issueReply(*asJSON, *full, next, ok, "", "", "", handed{}, cads...)
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
					return fullReply(*asJSON, err)
				} else if err != nil {
					return Reply{}, err
				}
			}
			fanout, wt := "", ""
			if ok {
				if err := restoreAnswers(c, s, &took, *worktree); err != nil {
					return Reply{}, err
				}
				fanout = c.fanOut(s, took.Number)
				if *worktree && !took.Parent {
					wt = issues.Worktree(c.Workspace, took.Number)
				}
				// What waits for it, so the box can tell which of them need
				// what it may leave over.
				if took.Blocks, err = s.Dependents(took.Number); err != nil {
					return Reply{}, err
				}
				// The Stop hook holds the box to closing what it took; a
				// parent's box coordinates its tree and closes nothing itself.
				if !took.Parent {
					if err := recordTake(c, took.Number); err != nil {
						return Reply{}, fmt.Errorf("took #%d, but recording it for the Stop hook: %w", took.Number, err)
					}
				}
			}
			var h handed
			if ok {
				h = c.handOver(took)
			}
			return issueReply(*asJSON, false, took, ok, issues.Branch(took.Number), wt, fanout, h, started...)
		},
	})
	register(Command{
		Name:    "issue tree",
		Class:   interactive,
		Usage:   "issue tree [ROOT] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "list the open queue and estimate when its last issue closes",
		Details: fmt.Sprintf("list every open se issue, each indented under its parent: its number, where it stands (ready, claimed, blocked and by what), how many of its sub-issues are closed, its labels and its title. With ROOT, list ROOT and every issue below it, open or closed. Then estimate when the last open one closes, from what the fleet measured over the last %s (PaceWindow), read as the retro reads it: the se issues merged an hour, and their claim-to-merge times (p50, p90) from the landing answers; how many run at once (the leaves in flight now that are not stuck, or the merges an hour times the p50, whichever is more); and the critical path, the longest chain of open work that must run in a row (blocked-by links, an ancestor's counting for its whole tree, and a review gate after its tree). The estimate is the larger of the critical path end to end and the open work spread over those running at once, at the p50 and at the p90 time; it names the critical path, and how long the work takes at the window's pace, idle hours and all. --json answers {\"issues\":[...],\"queue\":{...}} with the numbers.", issues.Span(issues.PaceWindow.Minutes())),
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
			q, open, err := s.Queue(root, issues.PaceWindow)
			if err != nil {
				return Reply{}, err
			}
			nodes := open
			if root > 0 {
				if nodes, err = s.TreeOf(root); err != nil {
					return Reply{}, err
				}
				why := map[int]string{}
				for _, n := range open {
					why[n.Number] = n.Why
				}
				for k := range nodes {
					nodes[k].Why = why[nodes[k].Number]
				}
			}
			if *asJSON {
				data, err := json.Marshal(struct {
					Issues []issues.Node `json:"issues"`
					Queue  issues.Queue  `json:"queue"`
				}{nodes, q})
				return Reply{Text: string(data)}, err
			}
			lines := make([]string, len(nodes))
			for k, n := range nodes {
				lines[k] = n.Line()
			}
			if len(nodes) == 0 {
				lines = []string{"No se issue is open."}
			}
			return Reply{Text: strings.Join(lines, "\n") + "\n\n" + q.Text()}, nil
		},
	})
	register(Command{
		Name:    "issue new",
		Class:   batch,
		Usage:   "issue new --title T (--body B | --body-file PATH) --blocked-by N,M|none [--parent N | --manifest] [--blocks N,M] [--review] [--final] [--person] [--allow-duplicate] [--skills NAME,NAME] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "create an se issue in a manifest, with its blockers",
		Details: fmt.Sprintf("create an se issue, linked as blocked by each issue --blocked-by names (GitHub's native links), and name it. All work moves in manifests: a manifest is an issue at the top on one topic whose sub-issues are its work, landing as one PR, its leaves together about %s (issues.manifest/config/target), and boxes take only manifests. --parent N files it into a manifest (a sub-issue of N); --manifest makes it a new manifest itself, labelled se-manifest, whose leaves follow with --parent; without either it goes into the open misc manifest (labelled se-misc), which takes new issues for that time from its creation, after which the next one opens.", issues.Span(issueConfig().ManifestTarget.Minutes())) + " --blocks links each issue it names as blocked by the new one: those dependents of a box's issue that need what is left of it. --review labels it se-review; --final labels it se-final, its last attempt: never superseded again. --person makes it an issue for a person: labelled se-person and assigned to the owner, it waits for them, and its body opens with what they decide. --skills names the skills its work needs, each a folder of src/plugin/skills in the workspace, in one marked line of its body: the take hands each over (se help issue pull). A name that is an agent's role (work, coordination, review, retro, overhaul, or the agent's own name) is left out of that line, since the take names the agent that holds it. It refuses a title an open se issue under the same --parent (or at the top) has already, naming it, unless --allow-duplicate is given. An issue for a person stands at the top, in no manifest. A ready issue, one nothing open blocks, fires the routine once. In a box it refuses, writing nothing: a box opens no issue, its work ends in a PR (se issue land) or a supersede (se issue supersede); retros, reviews and overhauls file theirs through their own commands.",
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
			final := fs.Bool("final", false, "label it se-final: its last attempt, never superseded again")
			person := fs.Bool("person", false, "make it an issue for a person: label it se-person and assign it to the owner")
			manifest := fs.Bool("manifest", false, "make it a new manifest, labelled se-manifest: its leaves follow with --parent")
			skills := fs.String("skills", "", "the skills its work needs, as `NAME,NAME`: a take hands each over")
			allowDuplicate := fs.Bool("allow-duplicate", false, "create it although an open se issue under the same parent has its title")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			// A box opens no issue: refused before anything is read or written.
			if c.isBox() {
				return Reply{}, errBoxOpensNoIssue
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
			if *manifest && (*parent > 0 || *person) {
				return Reply{}, fmt.Errorf("--manifest makes an issue at the top: it takes neither --parent nor --person")
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
			if given["skills"] {
				names, err := guidance.Parse(*skills)
				if err != nil {
					return Reply{}, err
				}
				// A role an agent holds is no skill: the take names its agent.
				names = issues.Skills(names)
				if _, err := guidance.Read(c.Disk, c.seRoot(), names); err != nil {
					return Reply{}, err
				}
				*body = guidance.With(*body, names)
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			// No bare issues: without --parent or --manifest it goes into the
			// open misc manifest, or the next one.
			misc := 0
			if *parent == 0 && !*manifest && !*person {
				if misc, err = s.Misc(); err != nil {
					return Reply{}, err
				}
				*parent = misc
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
			if *manifest {
				labels = append(labels, issues.ManifestLabel)
			}
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
			// Filed into no manifest, it went into the misc manifest, which
			// it may have opened.
			if *parent == 0 && made.In() > 0 {
				misc, *parent = made.In(), made.In()
			}
			fanout := ""
			if ready {
				fanout = c.fanOut(s, 0)
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
					Manifest  bool   `json:"manifest,omitempty"`
					Misc      bool   `json:"misc,omitempty"`
					Fanout    string `json:"fanout,omitempty"`
				}{made.Number, made.URL, append([]int{}, blockers...), *parent, dependents, *review, *final, *person, *manifest, misc > 0, fanout})
				return Reply{Text: string(data)}, err
			}
			text := fmt.Sprintf("Created #%d %s\n%s", made.Number, made.Title, made.URL)
			switch {
			case misc > 0:
				text += fmt.Sprintf("\nFiled into the misc manifest #%d: it named no --parent.", misc)
			case *parent > 0:
				text += fmt.Sprintf("\nA sub-issue of #%d.", *parent)
			case *manifest:
				text += fmt.Sprintf("\nA new manifest, labelled %s: file its leaves with --parent %d.", issues.ManifestLabel, made.Number)
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
				text += "\nLabelled " + issues.FinalLabel + ": its last attempt, never superseded again."
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
		Class:   batch,
		Usage:   "issue land --answers FILE [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "check and land issue-N: a leaf into its manifest, else one PR",
		Details: "on an issue-N branch: refuse unless FILE answers every question in spec/landing.yaml (YAML keyed by their keys, none empty, none unknown; a relative FILE is read from the workspace), and refuse an issue with open sub-issues. A leaf inside a manifest (an issue with a parent) lands into the manifest's branch: merge origin's issue-N and the manifest's issue-M into it (never a rebase), pass tests/check.sh, push it to both, post the answers on the leaf with its facts (its time from claim to land among them) and close it; a leaf gets no PR of its own. An issue at the top (a manifest whose leaves are all closed, a retro, an overhaul) lands to main: merge origin's branch and origin/main in, pass tests/check.sh, refuse a tree the battery did not record as passed and a branch main moved past meanwhile, commit the battery's record (battery/config/passed, which names the tree) with the work, so CI trusts it (se fleet trust), push, post the answers on the issue (or update the ones posted before), open its PR against main (Fixes #N, and the battery's profile), or find it open with its profile brought up to date, and turn on auto-merge (squash), recording the PR, auto-merge on, in .se/.runtime/box.json, which se hook stop trusts before it asks GitHub; a manifest whose branch holds nothing main does not closes with no PR.",
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
			// The Stop hook trusts this record before it asks GitHub.
			if err := recordLand(c, l.Issue, l.Number); err != nil {
				return Reply{}, fmt.Errorf("landed PR #%d (%s), but recording it for the Stop hook: %w", l.Number, l.URL, err)
			}
			if *asJSON {
				data, err := json.Marshal(l)
				return Reply{Text: string(data)}, err
			}
			switch {
			case l.Manifest > 0:
				return Reply{Text: fmt.Sprintf("Landed #%d into %s, the branch of manifest #%d, and closed it: a leaf gets no PR. The manifest lands as one PR once its leaves are done.", l.Issue, l.Into, l.Manifest)}, nil
			case l.Closed:
				return Reply{Text: fmt.Sprintf("Closed #%d: its leaves are all closed and its branch holds nothing main does not, so there is no PR.", l.Issue)}, nil
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

// errBoxOpensNoIssue is se issue new's refusal in a box. The owner's rule: a
// box's outcome is a PR, a supersede or a close --fixed-by, never a new
// issue; retros, reviews and overhauls file theirs through their own commands.
var errBoxOpensNoIssue = errors.New("a box opens no issue: its work ends in a PR (se issue land), or, where it cannot land one, a supersede (se issue supersede) that carries what is left. Retros, reviews and overhauls file issues through their own commands")

func init() {
	register(Command{
		Name:    "issue keep",
		Class:   batch,
		Usage:   "issue keep [--for D] [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "stay with an issue-N branch's PR until it merges",
		Details: "on an issue-N branch whose PR se issue land opened: a box keeps its PR until it merges. The PR merges once its own CI is green, up to date with main or not; only a conflict holds it back. Every minute, for D at most (default 8m, so one call fits a tool's timeout), it looks at the PR; whenever main has moved past the branch on origin, it merges origin/main in (never a rebase), passes tests/check.sh, commits the battery's record and pushes, as se issue land does, so the PR is checked again against the main it merges into and CI trusts it. It says when the PR merged, or another box took the issue over, or that it is still open: run it again. A merge that conflicts, a failing check and a PR closed unmerged are errors to fix, then land again (with --json: {\"issue\",\"pr\",\"url\",\"merged\",\"taken_over\",\"updated\"}).",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "issue keep")
			within := fs.Duration("for", 8*time.Minute, "keep the PR this long (`D`) at most before answering")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			k, err := s.Keep(c.Workspace, *within, func(dir string) error { return c.Check(c.Proc, dir) })
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(k)
				return Reply{Text: string(data)}, err
			}
			text := fmt.Sprintf("PR #%d of issue-%d is still open: run se issue keep again.", k.PR, k.Issue)
			switch {
			case k.Merged:
				text = fmt.Sprintf("PR #%d of issue-%d merged: the box is done with it.", k.PR, k.Issue)
			case k.TakenOver:
				text = fmt.Sprintf("Another box took issue #%d over: PR #%d is its now.", k.Issue, k.PR)
			}
			if k.Updated > 0 {
				text += fmt.Sprintf(" It merged main in, checked and pushed %d time(s).", k.Updated)
			}
			return Reply{Text: text + "\n" + k.URL}, nil
		},
	})
}

func init() {
	register(Command{
		Name:    "issue review",
		Class:   batch,
		Usage:   "issue review pass|fail N --report PATH [--json] [--repo OWNER/NAME]",
		Group:   "Issues",
		Summary: "pass or fail a gate whose sub-issues closed, by its report",
		Details: fmt.Sprintf("review N, an se-review parent whose sub-issues have closed, as an agent that worked none of its tree, with the report in the JSON file PATH (spec/review.md). It refuses a pass where a requirement lacks evidence, and a report without its checked-and-clean list. Every finding becomes an se-final issue: a blocking one a sub-issue of N, a non-blocking one a sub-issue of the review's one manifest of findings (Findings of the review of #N, se-manifest and se-final) (at most %d, issues/config/max-filed). pass posts the report and closes N; fail posts it, and N waits for its fixes. A re-review finding that repeats an earlier blocker is an accepted repeat: it files nothing, the report names it, and a fail whose blocking findings are all repeats closes N.", issueConfig().MaxFiled),
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
			if err := checkRan(rep); err != nil {
				return Reply{}, err
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
			case r.Passed:
				lines = append(lines, fmt.Sprintf("Passed #%d: the report is on it, and it is closed.", n))
			case r.Closed:
				lines = append(lines, fmt.Sprintf("#%d's re-review found only earlier blockers' problems again (%s): the report names them as accepted repeats, and it is closed.", n, numbers(r.Accepted)))
			default:
				lines = append(lines, fmt.Sprintf("Failed #%d: the report is on it, and its blocking findings are sub-issues of it:", n))
			}
			for _, f := range r.Fixes {
				lines = append(lines, fmt.Sprintf("#%d %s\n%s", f.Number, f.Title, f.URL))
			}
			if !r.Closed && len(r.Accepted) > 0 {
				lines = append(lines, "Accepted repeats, blocking no more: "+numbers(r.Accepted)+".")
			}
			if len(r.Filed) > 0 {
				lines = append(lines, fmt.Sprintf("Filed, not blocking, as sub-issues of the manifest #%d, all %s:", r.Manifest, issues.FinalLabel))
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
		Class:   batch,
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
			text := strings.TrimRight(b.Text(), "\n")
			if ran := c.reused(reuse.Reviewer, reviewerIntro); ran != "" {
				text += "\n\n" + ran
			}
			return Reply{Text: text}, nil
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
		cfg, err := issues.Configured()
		if err != nil {
			return issues.Source{}, err
		}
		return issues.Source{Repo: *repo, GitHub: c.GitHub, Clock: c.Clock, Disk: c.Disk, Proc: c.Proc, Waits: waits, Box: c.sessionID(), Config: &cfg}, nil
	}, asJSON
}

// handed is what a take handed over: the skills its issue names, and the
// text that carries them.
type handed struct {
	Skills []guidance.Skill
	Text   string
}

// issueReply shows the issue, or that there was none; branch names the branch
// a take claimed, worktree the command that makes its worktree where the take
// checked nothing out, fanout what its fan-out did, h the skills it handed
// over, and cads where the retro and overhaul cadences stand. A take passes
// the one cadence that started its issue, if any; full shows a plain pull's
// body, which a take always shows. Every body it shows is issues.Shown.
func issueReply(asJSON, full bool, i issues.Issue, ok bool, branch, worktree, fanout string, h handed, cads ...issues.Cadence) (Reply, error) {
	i.Body = issues.Shown(i.Body)
	if asJSON {
		answer := struct {
			Ready     bool             `json:"ready"`
			Issue     *issues.Issue    `json:"issue,omitempty"`
			Branch    string           `json:"branch,omitempty"`
			Worktree  string           `json:"worktree,omitempty"`
			Fanout    string           `json:"fanout,omitempty"`
			Agent     string           `json:"agent,omitempty"`
			Skills    []guidance.Skill `json:"skills,omitempty"`
			Guidance  string           `json:"guidance,omitempty"`
			Retros    *issues.Cadence  `json:"retros,omitempty"`
			Overhauls *issues.Cadence  `json:"overhauls,omitempty"`
		}{Ready: ok, Fanout: fanout, Skills: h.Skills, Guidance: h.Text}
		for k := range cads {
			if cads[k].Kind == "overhaul" {
				answer.Overhauls = &cads[k]
			} else {
				answer.Retros = &cads[k]
			}
		}
		if ok {
			answer.Issue, answer.Branch, answer.Worktree, answer.Agent = &i, branch, worktree, issues.KindOf(i).Type()
		}
		data, err := json.Marshal(answer)
		return Reply{Text: string(data)}, err
	}
	if branch == "" {
		return pulled(i, ok, full, cads), nil
	}
	var head string
	t := i.Takeover
	switch {
	case t != nil && t.PR != 0 && t.Stale == "":
		head = fmt.Sprintf("Took over #%d %s, on branch %s: its PR #%d conflicts with main (takeover %d).\n%s\n%s\nMerge origin/main into %s (never rebase, never force-push), resolve the conflict, and land it again with se issue land.",
			i.Number, i.Title, branch, t.PR, t.Count, i.URL, t.URL, branch)
	case t != nil:
		head = fmt.Sprintf("Took over #%d %s, on branch %s as it stands: it was stuck, %s (takeover %d).\n%s", i.Number, i.Title, branch, t.Stale, t.Count, i.URL)
		if t.URL != "" {
			head += "\n" + t.URL
		}
		head += fmt.Sprintf("\nMerge origin/main into %s (never rebase, never force-push), continue the branch and its PR, make it green, and land it again with se issue land.", branch)
	case len(cads) > 0:
		cad := cads[0]
		head = fmt.Sprintf("Started the unattended %s #%d %s, as %d %s closed since the last one (the cadence is %d), and took it, on branch %s.\n%s",
			cad.Kind, i.Number, i.Title, cad.Closed, cad.Counts(), cad.Every, branch, i.URL)
	default:
		head = fmt.Sprintf("Took #%d %s, on branch %s.\n%s", i.Number, i.Title, branch, i.URL)
	}
	if branch != "" {
		head += fmt.Sprintf("\nIts agent: %s.", issues.KindOf(i).Type())
		head += answersLine(t)
	}
	if worktree != "" {
		head += "\n\nIts sub-agent works in its own worktree:\n" + worktree
	}
	if branch != "" && len(i.Blocks) > 0 {
		head += fmt.Sprintf("\nIt blocks %s. What you cannot finish goes into a supersede (se issue supersede), which they then wait on.", numbers(i.Blocks))
	}
	if fanout != "" {
		head += "\n" + fanout
	}
	if i.Parent {
		head += fmt.Sprintf("\n\n#%d is a parent: it holds no work. Its agent, %s, is the box itself: coordinate its tree with se issue pull --in %d --take", i.Number, issues.KindOf(i).Type(), i.Number)
	}
	text := strings.TrimRight(head+"\n\n"+i.Body, "\n")
	if h.Text != "" {
		text += "\n\n" + h.Text
	}
	return Reply{Text: text}, nil
}

// pulled answers a plain issue pull, which takes nothing. Typed, it names the
// issue, its link, why it is at the top and where each cadence stands, a line
// each, and the body under them where full asks for it. Pressed, it is short:
// the same lines but the body, and the cadences in one line.
func pulled(i issues.Issue, ok, full bool, cads []issues.Cadence) Reply {
	var cadences []string
	for _, cad := range cads {
		cadences = append(cadences, cad.Line())
	}
	head := []string{"No se issue is ready."}
	if ok {
		head = []string{fmt.Sprintf("#%d %s", i.Number, i.Title), i.URL}
		if i.Picked != "" {
			head = append(head, i.Picked)
		}
	}
	short := head
	if line := issues.Briefly(cads); line != "" {
		short = append(short[:len(short):len(short)], line)
	}
	text := strings.Join(head, "\n")
	if ok && i.Parent {
		text += fmt.Sprintf("\n#%d is a parent: it holds no work. Its agent, %s, is the box itself: coordinate its tree with se issue pull --in %d --take", i.Number, issues.KindOf(i).Type(), i.Number)
	}
	if ok && full && i.Body != "" {
		text += "\n\n" + i.Body + "\n"
	}
	if len(cadences) > 0 {
		text += "\n" + strings.Join(cadences, "\n")
	}
	return Reply{Text: text, Short: strings.Join(short, "\n")}
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
		return fullReply(asJSON, err)
	}
	if err != nil {
		return Reply{}, err
	}
	worktree := ""
	var h handed
	if ok {
		if err := restoreAnswers(c, s, &took, true); err != nil {
			return Reply{}, err
		}
		worktree = issues.Worktree(c.Workspace, took.Number)
		h = c.handOver(took)
	}
	took.Body = issues.Shown(took.Body)
	if asJSON {
		answer := struct {
			Ready    bool             `json:"ready"`
			Closed   bool             `json:"closed"`
			Issue    *issues.Issue    `json:"issue,omitempty"`
			Branch   string           `json:"branch,omitempty"`
			Worktree string           `json:"worktree,omitempty"`
			Agent    string           `json:"agent,omitempty"`
			Skills   []guidance.Skill `json:"skills,omitempty"`
			Guidance string           `json:"guidance,omitempty"`
			Review   []reviewAt       `json:"review"`
			Land     bool             `json:"land,omitempty"`
		}{Ready: ok, Closed: tr.Closed, Skills: h.Skills, Guidance: h.Text, Review: reviews(c, tr), Land: tr.Land}
		if tr.Land {
			// Every leaf is closed: the coordinator lands the manifest from
			// its branch, checked out in its own worktree.
			answer.Branch, answer.Worktree = issues.Branch(root), issues.Worktree(c.Workspace, root)
		}
		if ok {
			answer.Issue, answer.Branch, answer.Worktree, answer.Agent = &took, issues.Branch(took.Number), worktree, issues.KindOf(took).Type()
		}
		data, err := json.Marshal(answer)
		return Reply{Text: string(data)}, err
	}
	if !ok {
		work := tr
		work.Review = nil
		text := treeText(work) + reviewText(c, tr)
		if tr.Land {
			text += "\n\nLand it from its branch in its own worktree, with se issue land there:\n" + issues.Worktree(c.Workspace, root)
		}
		return Reply{Text: text}, nil
	}
	did := "Took #%d %s, on branch %s.\n%s\nIts agent: %s.\n\nWork in its own worktree:\n%s"
	if took.Takeover != nil {
		did = "Took over #%d %s, on branch %s as it stands: it was stuck.\n%s\nIts agent: %s.\n\nContinue the branch and its PR in its own worktree:\n%s"
	}
	text := fmt.Sprintf(did, took.Number, took.Title, issues.Branch(took.Number), took.URL, issues.KindOf(took).Type(), worktree) + answersLine(took.Takeover) + reviewText(c, tr)
	text = strings.TrimRight(text+"\n\n"+took.Body, "\n")
	if h.Text != "" {
		text += "\n\n" + h.Text
	}
	return Reply{Text: text}, nil
}

// restoreAnswers writes the landing answers a takeover's issue has on it back
// to the answers file beside the leaf's checkout (its own worktree where
// worktree is set), and names that file in took's takeover.
func restoreAnswers(c *Call, s issues.Source, took *issues.Issue, worktree bool) error {
	if took.Takeover == nil || took.Parent {
		return nil
	}
	path := issues.AnswersFile(c.Workspace, took.Number, worktree)
	restored, err := s.RestoreAnswers(took.Number, path)
	if err != nil {
		return fmt.Errorf("took over #%d, but restoring its landing answers: %w", took.Number, err)
	}
	if restored {
		t := *took.Takeover
		t.Answers = path
		took.Takeover = &t
	}
	return nil
}

// answersLine names the answers file a takeover wrote back, if any.
func answersLine(t *issues.Takeover) string {
	if t == nil || t.Answers == "" {
		return ""
	}
	return "\nIts landing answers, as its last land posted them, are in " + t.Answers + ": bring them up to date, and land with --answers " + t.Answers + "."
}

// pausedReply answers a take while the fleet is paused (with --json:
// {"ready":false,"paused":true,"why"}): the box takes nothing and ends.
func pausedReply(asJSON bool) (Reply, error) {
	if asJSON {
		data, err := json.Marshal(map[string]any{"ready": false, "paused": true, "why": issues.PausedWhy})
		return Reply{Text: string(data)}, err
	}
	return Reply{Text: "No take: " + issues.PausedWhy + "."}, nil
}

// fullReply answers a box's take refused because it runs its cap of
// sub-agents (with --json: {"ready":false,"full":true}).
func fullReply(asJSON bool, err error) (Reply, error) {
	if asJSON {
		data, jerr := json.Marshal(map[string]any{"ready": false, "full": true, "why": err.Error()})
		return Reply{Text: string(data)}, jerr
	}
	return Reply{Text: "No take: " + err.Error() + "."}, nil
}

// treeText says where a tree stands.
func treeText(tr issues.Tree) string {
	if tr.Closed {
		return fmt.Sprintf("#%d is closed.", tr.Root)
	}
	if tr.Why != "" {
		return fmt.Sprintf("Nothing inside #%d is ready: %s.", tr.Root, tr.Why)
	}
	if tr.Land {
		return fmt.Sprintf("Every leaf of #%d is closed: the manifest lands, as one PR from %s.", tr.Root, issues.Branch(tr.Root))
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
// reviewer's fresh worktree and the agent that reviews it.
type reviewAt struct {
	issues.Issue
	Worktree string `json:"worktree"`
	Agent    string `json:"agent"`
}

func reviews(c *Call, tr issues.Tree) []reviewAt {
	out := []reviewAt{}
	for _, i := range tr.Review {
		out = append(out, reviewAt{i, tr.ReviewWorktree(c.Workspace, i.Number), issues.KindNamed("gate").Type()})
	}
	return out
}

// reviewText names, after a take, the parents ready for review and where
// their reviewers work.
func reviewText(c *Call, tr issues.Tree) string {
	text := ""
	for _, r := range reviews(c, tr) {
		text += fmt.Sprintf("\n\nReady for review: #%d %s\n%s\nIts agent, %s, worked none of its tree and works in a fresh worktree:\n%s", r.Number, r.Title, r.URL, r.Agent, r.Worktree)
	}
	return text
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
