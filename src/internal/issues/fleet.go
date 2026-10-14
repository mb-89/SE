package issues

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// The kinds of finding se fleet check lists, in the order it lists them and
// the box, se:coordinator, works them. spec/coordination.md says what each is.
const (
	StalledRoot     = "stalled root"
	ConflictedPR    = "conflicted PR"
	RedPR           = "red PR"
	GreenUnmerged   = "green but unmerged"
	NoPR            = "no PR"
	StaleManifest   = "stale manifest"
	LeftoverClaim   = "leftover claim"
	ImpossibleBlock = "impossible block"
	BareIssue       = "bare issue"
	WaitingOnPerson = "waiting on a person"
)

// Kinds is every kind of finding, in the order se fleet check lists them.
var Kinds = []string{StalledRoot, ConflictedPR, RedPR, GreenUnmerged, NoPR, StaleManifest, LeftoverClaim, ImpossibleBlock, BareIssue, WaitingOnPerson}

// Grace is how long the prune workflow has to delete a leftover claim of a
// closed issue before se fleet fix reports it.
var Grace = 24 * time.Hour

// Quiet is how long claimed work goes without a push or a takeover before se
// fleet check finds it not moving, by the one rule Source.quiet.
var Quiet = time.Hour

// Finding is one thing se fleet check found broken.
type Finding struct {
	Kind string `json:"kind"`
	// Cause is, for a stalled root, the finding on the root itself.
	Cause string `json:"cause,omitempty"`
	Issue int    `json:"issue"`
	PR    int    `json:"pr,omitempty"`
	What  string `json:"what"`
	// Remedy is the command that fixes it, or why there is none.
	Remedy string `json:"remedy"`
	// Holds is the open issues that wait on it.
	Holds []int `json:"holds,omitempty"`
	// head is the commit a takeover finds; url and nodeID are the PR's.
	head, url, nodeID string
	// autoMerge is true for a PR whose auto-merge is on already.
	autoMerge bool
	// judgment is true where only a person can decide the fix.
	judgment bool
	// spent is true for a leftover claim whose branch main holds whole:
	// deleting it loses nothing.
	spent bool
	// prunable is true for a leftover claim of a closed issue with no open
	// PR: the prune workflow deletes its branch. closed is when it closed.
	prunable bool
	closed   time.Time
	// key names the finding in the record its fix leaves.
	key string
	// id is GitHub's id of a bare issue, which the sub-issues link takes.
	id int64
}

// cause is the kind of the finding on the issue itself.
func (f Finding) cause() string {
	if f.Cause != "" {
		return f.Cause
	}
	return f.Kind
}

// takeover says whether the fix is a takeover of the claimed issue, by a box
// that merges main into its branch, makes it green and lands it again.
func (f Finding) takeover() bool {
	switch f.cause() {
	case ConflictedPR, RedPR, NoPR:
		return true
	}
	return false
}

func (f *Finding) setRemedy() {
	switch {
	case f.Kind == WaitingOnPerson:
		f.Remedy = "none: it waits for a person"
	case f.takeover():
		f.Remedy = fmt.Sprintf("se issue pull --take %d, merge origin/main into %s, make it green, se issue land", f.Issue, Branch(f.Issue))
	case f.cause() == GreenUnmerged && !f.autoMerge:
		f.Remedy = "se fleet fix turns auto-merge on"
	case f.prunable:
		f.Remedy = fmt.Sprintf("the prune workflow deletes %s; se fleet check reports it if it is still there a day after #%d closed", Branch(f.Issue), f.Issue)
	case f.Kind == BareIssue:
		f.Remedy = "se fleet fix files it into the open misc manifest"
	case f.Kind == StaleManifest:
		f.Remedy = fmt.Sprintf("se fleet fix merges origin/main into %s, as se fleet refresh does; where it conflicts, merge it by hand (never rebase)", Branch(f.Issue))
	case f.spent:
		f.Remedy = "se fleet fix deletes " + Branch(f.Issue) + ": main holds all its commits"
	default:
		f.Remedy = "none se applies by itself; se fleet check reports it"
	}
}

// ref is one issue-<n> branch on origin.
type ref struct {
	Ref    string `json:"ref"`
	Object struct {
		SHA string `json:"sha"`
	} `json:"object"`
}

// Check reads GitHub and lists what is broken in the fleet, in the order of
// Kinds, lowest issue first within a kind. It writes nothing but what every
// se issue command writes: parents whose sub-issues are all closed close.
func (s Source) Check() ([]Finding, error) {
	all, t, err := s.survey()
	if err != nil {
		return nil, err
	}
	return s.check(all, t)
}

// CheckFanOut is Check, and then se fleet check's part in the fan-out on the
// same survey: a fan-out the routine refused, kept on the alive claims, fires
// once its retry time has passed and the fleet still needs the box. fire is the fire itself; the
// line says what happened, empty where no refused fan-out is kept.
func (s Source) CheckFanOut(fire func() Shot) ([]Finding, string, error) {
	all, t, err := s.survey()
	if err != nil {
		return nil, "", err
	}
	found, err := s.check(all, t)
	if err != nil {
		return nil, "", err
	}
	return found, s.retryFanOut(all, t, fire), nil
}

// check is Check on a survey already read.
func (s Source) check(all []Status, t tree) ([]Finding, error) {
	var claims, stale, out []Finding
	if err := parallel([]func() error{
		func() (err error) { claims, err = s.claimFindings(all, t); return err },
		func() (err error) { stale, err = s.staleManifests(t); return err },
		func() (err error) { out, err = s.leftovers(t); return err },
	}); err != nil {
		return nil, err
	}
	out = append(out, stale...)
	deps := t.deps
	out = append(out, s.impossible(t)...)

	// What each open issue waits on, at the end of its links: the claimed
	// leaves and the se-person issues it cannot move without.
	byNum := map[int]Status{}
	ready := false
	for _, st := range all {
		byNum[st.Number] = st
		ready = ready || (st.Above == 0 && st.Ready())
	}
	stop := func(n int) bool { return byNum[n].claimed || t.byNum[n].labelled(PersonLabel) }
	blockers := func(n int) []int {
		var bs []int
		for _, d := range deps[n] {
			if _, ok := t.byNum[d.Number]; ok && d.State == "open" {
				bs = append(bs, d.Number)
			}
		}
		return bs
	}
	edges := func(n int) []int {
		e := blockers(n)
		for p := t.above[n]; p != 0; p = t.above[p] {
			e = append(e, blockers(p)...)
		}
		for _, c := range t.subs[n] {
			if _, ok := t.byNum[c.Number]; ok {
				e = append(e, c.Number)
			}
		}
		return e
	}
	holds := map[int][]int{}
	for _, n := range t.numbers() {
		if stop(n) {
			continue
		}
		seen := map[int]bool{n: true}
		for queue := edges(n); len(queue) > 0; queue = queue[1:] {
			m := queue[0]
			if seen[m] {
				continue
			}
			seen[m] = true
			if stop(m) {
				holds[m] = append(holds[m], n)
				continue
			}
			queue = append(queue, edges(m)...)
		}
	}
	for _, n := range t.numbers() {
		if t.byNum[n].labelled(PersonLabel) {
			out = append(out, Finding{
				Kind: WaitingOnPerson, Issue: n, Holds: holds[n],
				What: fmt.Sprintf("#%d waits for a person (%s)%s", n, PersonLabel, holding(holds[n])),
			})
		}
	}
	// An issue filed by an se that predates manifests stands in none, and no
	// box takes it: it goes into the open misc manifest. Bare is set only on
	// an unclaimed issue at the top that nothing holds.
	for _, st := range all {
		if st.Bare == BareWhy {
			out = append(out, Finding{
				Kind: BareIssue, Issue: st.Number, id: t.byNum[st.Number].ID, key: "bare-issue",
				What: fmt.Sprintf("#%d stands in no manifest, and boxes take only manifests", st.Number),
			})
		}
	}
	for _, f := range claims {
		if !ready && len(holds[f.Issue]) > 0 {
			f.Cause, f.Kind, f.Holds = f.Kind, StalledRoot, holds[f.Issue]
			f.What = fmt.Sprintf("nothing is ready, and %s wait on #%d: %s", names(f.Holds), f.Issue, f.What)
		}
		out = append(out, f)
	}
	rank := map[string]int{}
	for k, kind := range Kinds {
		rank[kind] = k
	}
	sort.SliceStable(out, func(a, b int) bool {
		if rank[out[a].Kind] != rank[out[b].Kind] {
			return rank[out[a].Kind] < rank[out[b].Kind]
		}
		return out[a].Issue < out[b].Issue
	})
	for k := range out {
		out[k].setRemedy()
	}
	return out, nil
}

func names(ns []int) string {
	words := make([]string, len(ns))
	for k, n := range ns {
		words[k] = "#" + strconv.Itoa(n)
	}
	return strings.Join(words, ", ")
}

func holding(ns []int) string {
	if len(ns) == 0 {
		return ""
	}
	return ", holding up " + names(ns)
}

// claimFindings is what is stuck about each claimed leaf, read from the
// survey's branches and open PRs.
func (s Source) claimFindings(all []Status, t tree) ([]Finding, error) {
	byRef := toMain(t.pulls)
	shas := map[string]string{}
	for _, r := range t.refs {
		shas[strings.TrimPrefix(r.Ref, "refs/heads/")] = r.Object.SHA
	}
	var claimed []Status
	for _, st := range all {
		if st.claimed {
			claimed = append(claimed, st)
		}
	}
	found, err := each(len(claimed), func(k int) (*Finding, error) {
		b := Branch(claimed[k].Number)
		p, ok := byRef[b]
		return s.claimFinding(claimed[k], p, ok, shas[b], t)
	})
	if err != nil {
		return nil, err
	}
	var out []Finding
	for _, f := range found {
		if f != nil {
			out = append(out, *f)
		}
	}
	return out, nil
}

// failed is the conclusions of a check run that make CI red.
var failed = map[string]bool{"failure": true, "timed_out": true, "cancelled": true, "action_required": true, "startup_failure": true}

// claimFinding is what is stuck about claimed leaf st, whose open PR is p
// where open is true, and whose branch is at sha; nil where its work is
// moving, or a takeover of it is. What t holds already is not read again.
func (s Source) claimFinding(st Status, p openPull, open bool, sha string, t tree) (*Finding, error) {
	n, b, pushed := st.Number, Branch(st.Number), st.pushed
	quiet, _, m, err := s.quiet(n, pushed, Quiet)
	if err != nil {
		return nil, err
	}
	since := "no push since " + pushed.UTC().Format(time.RFC3339)
	if pushed.IsZero() {
		since = "no push on record"
	}
	var f *Finding
	if !open {
		closed := t.shut[b]
		if t.shut == nil {
			owner, _, _ := strings.Cut(s.Repo, "/")
			if closed, err = api[closedPull](s, fmt.Sprintf("repos/%s/pulls?head=%s:%s&base=main&state=closed&per_page=100", s.Repo, owner, b), true); err != nil {
				return nil, err
			}
		}
		merged := false
		for _, c := range closed {
			merged = merged || c.Merged != nil
		}
		switch {
		case len(closed) > 0 && !merged:
			f = &Finding{
				Kind: LeftoverClaim, PR: closed[0].Number, key: "leftover-claim",
				What: fmt.Sprintf("%s claims #%d, but its PR #%d was closed unmerged", b, n, closed[0].Number),
			}
		case len(closed) == 0 && quiet:
			f = &Finding{Kind: NoPR, head: sha, What: fmt.Sprintf("%s has no PR, and %s", b, since)}
		}
	} else {
		if p, err = s.mergeability(p); err != nil {
			return nil, err
		}
		if p.dirty() {
			f = &Finding{Kind: ConflictedPR, What: fmt.Sprintf("PR #%d conflicts with main", p.Number)}
		} else {
			red, pending, err := t.runs.checks(s, p.Head.SHA)
			if err != nil {
				return nil, err
			}
			switch {
			case len(red) > 0 && quiet:
				f = &Finding{Kind: RedPR, What: fmt.Sprintf("PR #%d fails %s on its latest commit, and %s", p.Number, strings.Join(red, ", "), since)}
			case len(red) == 0 && !pending && p.Mergeable != nil && *p.Mergeable && p.AutoMerge == nil:
				f = &Finding{Kind: GreenUnmerged, What: fmt.Sprintf("PR #%d is green and merges, but auto-merge is off", p.Number)}
			case len(red) == 0 && !pending && p.Mergeable != nil && *p.Mergeable && quiet:
				f = &Finding{
					Kind: GreenUnmerged, autoMerge: true,
					What: fmt.Sprintf("PR #%d is green with auto-merge on, but sits unmerged (%s), and %s", p.Number, p.State, since),
				}
			}
		}
		if f != nil {
			f.PR, f.head, f.url, f.nodeID = p.Number, p.Head.SHA, p.URL, p.NodeID
			if f.Kind == GreenUnmerged {
				f.key = fmt.Sprintf("green-unmerged-%d", p.Number)
			}
		}
	}
	if f == nil {
		return nil, nil
	}
	f.Issue = n
	if f.takeover() {
		if m == nil {
			got, err := s.marks(n)
			if err != nil {
				return nil, err
			}
			m = &got
		}
		if m.takeovers > 0 && m.head == f.head && s.now().Sub(m.lastTakeover) < Quiet {
			return nil, nil
		}
	}
	return f, nil
}

// runs is the check runs read, by commit, so that each is read once.
type runs struct {
	mu   sync.Mutex
	read map[string]*checked
}

// checked is the check runs on one commit, read once.
type checked struct {
	once    sync.Once
	red     []string
	pending bool
	err     error
}

// checks is the check runs on commit sha as checks reads them, read the
// first time they are asked for.
func (r *runs) checks(s Source, sha string) (red []string, pending bool, err error) {
	r.mu.Lock()
	c, ok := r.read[sha]
	if !ok {
		c = &checked{}
		r.read[sha] = c
	}
	r.mu.Unlock()
	c.once.Do(func() { c.red, c.pending, c.err = s.checks(sha) })
	return c.red, c.pending, c.err
}

// checks reads the check runs on commit sha: the names of those that failed,
// and whether any is still running.
func (s Source) checks(sha string) (red []string, pending bool, err error) {
	got, err := api[struct {
		Runs []struct {
			Name       string `json:"name"`
			Status     string `json:"status"`
			Conclusion string `json:"conclusion"`
		} `json:"check_runs"`
	}](s, fmt.Sprintf("repos/%s/commits/%s/check-runs?per_page=100", s.Repo, sha), false)
	if err != nil {
		return nil, false, err
	}
	for _, r := range got[0].Runs {
		if r.Status != "completed" {
			pending = true
		} else if failed[r.Conclusion] {
			red = append(red, r.Name)
		}
	}
	return red, pending, nil
}

// leftovers is the issue-<n> branches whose issue is no open se issue. One
// whose issue is closed and that has no open PR is prunable: the prune
// workflow deletes it. Any other that main holds whole is spent: its fix
// deletes it.
func (s Source) leftovers(t tree) ([]Finding, error) {
	open := map[string]bool{}
	for _, p := range t.pulls {
		open[p.Head.Ref] = true
	}
	var stray []ref
	for _, r := range t.refs {
		b := strings.TrimPrefix(r.Ref, "refs/heads/")
		n, err := strconv.Atoi(strings.TrimPrefix(b, "issue-"))
		if err != nil || Branch(n) != b {
			continue
		}
		if _, ok := t.byNum[n]; !ok {
			stray = append(stray, r)
		}
	}
	found, err := each(len(stray), func(k int) (Finding, error) {
		r := stray[k]
		b := strings.TrimPrefix(r.Ref, "refs/heads/")
		n := atoi(strings.TrimPrefix(b, "issue-"))
		got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
		if err != nil {
			return Finding{}, err
		}
		i, why := got[0], ""
		switch {
		case i.PullRequest != nil:
			why = "a pull request"
		case i.State == "closed" && i.StateReason != "":
			why = "closed (" + strings.ReplaceAll(i.StateReason, "_", " ") + ")"
		case i.State == "closed":
			why = "closed"
		default:
			why = "not labelled " + Label
		}
		cmp, err := api[struct {
			AheadBy int `json:"ahead_by"`
		}](s, fmt.Sprintf("repos/%s/compare/main...%s?per_page=1", s.Repo, r.Object.SHA), false)
		if err != nil {
			return Finding{}, err
		}
		f := Finding{
			Kind: LeftoverClaim, Issue: n, head: r.Object.SHA, key: "leftover-claim",
			What: fmt.Sprintf("%s claims #%d, which is %s", b, n, why),
		}
		if i.State == "closed" && i.PullRequest == nil && !open[b] {
			f.prunable, f.closed = true, i.ClosedAt
			return f, nil
		}
		if cmp[0].AheadBy == 0 {
			f.spent, f.key = true, "leftover-branch"
			f.What += ", and main holds all its commits"
		}
		return f, nil
	})
	return found, err
}

// staleManifests is the open manifests whose branch, on origin with no open
// PR into main, lacks commits of main: se fleet refresh had not merged them
// in, or the merge conflicts.
func (s Source) staleManifests(t tree) ([]Finding, error) {
	var ns []int
	for _, n := range t.numbers() {
		if t.byNum[n].labelled(ManifestLabel) {
			ns = append(ns, n)
		}
	}
	ms := refreshable(ns, t.refs, t.pulls)
	found, err := each(len(ms), func(k int) (*Finding, error) {
		cmp, err := api[struct {
			AheadBy int `json:"ahead_by"`
		}](s, fmt.Sprintf("repos/%s/compare/%s...main?per_page=1", s.Repo, ms[k].sha), false)
		if err != nil || cmp[0].AheadBy == 0 {
			return nil, err
		}
		return &Finding{
			Kind: StaleManifest, Issue: ms[k].n, head: ms[k].sha,
			What: fmt.Sprintf("%s lacks %d commit(s) of main, which its leaves would each meet on their own", Branch(ms[k].n), cmp[0].AheadBy),
		}, nil
	})
	var out []Finding
	for _, f := range found {
		if f != nil {
			out = append(out, *f)
		}
	}
	return out, err
}

// impossible is the blocks no box can ever lift: a blocker closed as not
// planned, an open blocker no box works, and blockers in a cycle.
func (s Source) impossible(t tree) []Finding {
	var out []Finding
	repoURL := "/repos/" + s.Repo
	links := map[int][]int{}
	for _, n := range t.numbers() {
		if t.byNum[n].labelled(PersonLabel) {
			continue
		}
		for _, d := range t.deps[n] {
			ours := d.labelled(Label) && (d.RepositoryURL == "" || strings.HasSuffix(d.RepositoryURL, repoURL))
			switch {
			case d.State == "closed" && d.StateReason == "not_planned":
				out = append(out, Finding{
					Kind: ImpossibleBlock, Issue: n, key: fmt.Sprintf("impossible-block-%d", d.Number),
					What: fmt.Sprintf("#%d is blocked by #%d, which was closed as not planned", n, d.Number),
				})
			case d.State == "open" && !ours:
				out = append(out, Finding{
					Kind: ImpossibleBlock, Issue: n, judgment: true, key: fmt.Sprintf("impossible-block-%d", d.Number),
					What: fmt.Sprintf("#%d is blocked by %s, which is no %s issue, so no box moves it", n, d.URL, Label),
				})
			case d.State == "open":
				links[n] = append(links[n], d.Number)
			}
		}
	}
	// A cycle is named once, by its lowest issue: the shortest way back to
	// it through higher issues.
	for _, n := range t.numbers() {
		from := map[int]int{}
		var path []int
		for queue := []int{n}; len(queue) > 0 && path == nil; queue = queue[1:] {
			m := queue[0]
			for _, b := range links[m] {
				if b == n {
					for path = []int{n}; m != n; m = from[m] {
						path = append([]int{m}, path...)
					}
					path = append([]int{n}, path...)
					break
				}
				if _, seen := from[b]; !seen && b > n {
					from[b] = m
					queue = append(queue, b)
				}
			}
		}
		if path == nil {
			continue
		}
		words := make([]string, len(path))
		for k, m := range path {
			words[k] = "#" + strconv.Itoa(m)
		}
		out = append(out, Finding{
			Kind: ImpossibleBlock, Issue: n, judgment: true, key: "impossible-block-cycle",
			What: "a cycle of blocks: " + strings.Join(words, " is blocked by "),
		})
	}
	return out
}

// Fixed is what se fleet fix did about one finding.
type Fixed struct {
	Finding
	// Did says what was done, in a few words.
	Did string `json:"did"`
	// Take is true where the fix is a takeover, by its Remedy.
	Take bool `json:"take,omitempty"`
	// Failed is why the remedy failed, where it did; Did says so too.
	Failed string `json:"failed,omitempty"`
}

// Fix applies, in order, the remedy of every finding that needs no checkout:
// auto-merge goes on where it is off, a stale manifest's branch takes main
// in (refreshOne), a spent leftover branch is deleted, by
// a push from the checkout dir, the transport se issue land pushes through,
// and a bare issue is filed into the open misc manifest by a sub-issue link.
// Every other finding is reported, never filed: an issue is work, not a
// report (principle 12), and Fix writes no issue and no comment. A takeover
// is named for the next take. A remedy that fails is reported in its Fixed,
// and the remedies after it are still applied.
func (s Source) Fix(dir string, findings []Finding) []Fixed {
	var out []Fixed
	for _, f := range findings {
		x := Fixed{Finding: f}
		switch {
		case f.Kind == WaitingOnPerson:
			x.Did = "reported; it waits for a person"
		case f.takeover():
			x.Did, x.Take = "left to the next take: "+f.Remedy, true
		case f.Kind == StaleManifest:
			r := s.refreshOne(dir, f.Issue)
			x.Did, x.Failed = r.Did, r.Failed
		case f.prunable && s.now().Sub(f.closed) < Grace:
			x.Did = fmt.Sprintf("left to the prune workflow until a day after #%d closed", f.Issue)
		case f.prunable:
			x.What += ", and is still there a day after it closed: the prune workflow did not delete it"
			x.Did = "reported; the prune workflow did not delete it"
		default:
			if err := s.fix(dir, &x); err != nil {
				x.Failed = err.Error()
				x.Did = "failed: " + x.Failed
			}
		}
		out = append(out, x)
	}
	return out
}

func (s Source) fix(dir string, x *Fixed) error {
	f := x.Finding
	switch {
	case f.cause() == GreenUnmerged && !f.autoMerge:
		merged, err := s.autoMerge(pull{Number: f.PR, NodeID: f.nodeID, URL: f.url})
		if err != nil {
			return err
		}
		x.Did = fmt.Sprintf("turned auto-merge on for PR #%d", f.PR)
		if merged {
			x.Did = fmt.Sprintf("merged PR #%d, which had nothing left to wait for", f.PR)
		}
	case f.spent:
		if _, err := s.git(dir, "push", "-q", "origin", "--delete", Branch(f.Issue)); err != nil {
			return fmt.Errorf("deleting %s: %w", Branch(f.Issue), err)
		}
		x.Did = fmt.Sprintf("deleted %s at %s, which main holds whole", Branch(f.Issue), f.head)
	case f.Kind == BareIssue:
		m, err := s.FileInto()
		if err != nil {
			return err
		}
		if err := s.subIssue(m, f.id); err != nil {
			return fmt.Errorf("filing #%d into misc manifest #%d: %w", f.Issue, m, err)
		}
		x.Did = fmt.Sprintf("filed it into misc manifest #%d", m)
	default:
		x.Did = "reported; it has no remedy se applies by itself"
	}
	return nil
}

func atoi(s string) int {
	n, _ := strconv.Atoi(s)
	return n
}

// takeOverClaim takes over claimed leaf st, named by se issue pull --take N,
// where se fleet check finds it stuck: its branch is checked out as it stands.
// A takeover labels it se-final; a final issue stuck is taken over again.
func (s Source) takeOverClaim(dir string, st Status, t tree) (took Issue, ok bool, err error) {
	fs, err := s.claimFindings([]Status{st}, t)
	if err != nil {
		return Issue{}, false, err
	}
	if len(fs) == 0 || !fs[0].takeover() {
		return Issue{}, false, fmt.Errorf("#%d is not ready: %s, and nothing about it is stuck that a takeover fixes", st.Number, st.Why)
	}
	f := fs[0]
	m, err := s.marks(st.Number)
	if err != nil {
		return Issue{}, false, err
	}
	k := m.takeovers + 1
	// A conflict is no failure: it never makes an issue final.
	conflict := f.Kind == ConflictedPR
	heads := fmt.Sprintf("\n\n<!-- se:takeover %d -->\n<!-- se:takeover-head %s -->", k, f.head)
	body := fmt.Sprintf("Taken over: %s at %s. This box merges main into %s, makes it green and lands it again.", f.What, f.head, Branch(st.Number)) + heads + s.boxLine()
	won, err := s.markTakeover(st.Number, k, body)
	if err != nil {
		return Issue{}, false, err
	}
	if !won {
		return Issue{}, false, fmt.Errorf("#%d was taken over by another box just now", st.Number)
	}
	if !conflict {
		if err := s.finalize(st.Number); err != nil {
			return Issue{}, false, err
		}
	}
	if err := s.pickUp(dir, st.Number); err != nil {
		return Issue{}, false, err
	}
	took = st.Issue
	took.Takeover = &Takeover{PR: f.PR, URL: f.url, Count: k, Stale: f.What}
	return took, true, nil
}
