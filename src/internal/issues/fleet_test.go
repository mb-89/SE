// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"encoding/json"
	"fmt"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/github"
)

// noon is the recorded fleet's clock: pushes at 11:30 are recent, at 9:00 quiet.
var noon = time.Date(2026, 10, 13, 12, 0, 0, 0, time.UTC)

const (
	recent = "2026-10-13T11:30:00Z"
	quiet  = "2026-10-13T09:00:00Z"
)

// world is a fake repository o/r for se fleet check, seeded from recorded
// answers. Every open issue is blocked by nothing unless a test links it,
// and its last issue is #100, so what se fleet fix reports is #101 on.
type world struct {
	t *testing.T
	*github.Fake
}

// set records one answer more.
func (w *world) set(path, answer string) {
	w.t.Helper()
	seed(w.t, w.Fake, map[string]string{path: answer})
}

// said sets issue n's comments to the one body, made at at.
func (w *world) said(n int, body string, at time.Time) {
	w.t.Helper()
	data, err := json.Marshal([]comment{{ID: 1, Body: body, Created: at}})
	if err != nil {
		w.t.Fatal(err)
	}
	w.set(fmt.Sprintf("repos/o/r/issues/%d/comments", n), string(data))
}

// item is one issue as GitHub lists it: its labels after se, and how many
// sub-issues it has.
func item(n int, subs int, labels ...string) string {
	ls := `{"name":"se"}`
	for _, l := range labels {
		ls += fmt.Sprintf(`,{"name":%q}`, l)
	}
	return fmt.Sprintf(`{"number":%d,"title":"t%d","state":"open","html_url":"u%d","labels":[%s],"sub_issues_summary":{"total":%d}}`, n, n, n, ls, subs)
}

// dep is a blocker as GitHub's "blocked by" links list it.
func dep(n int, state, reason string, se bool) string {
	ls := `[]`
	if se {
		ls = `[{"name":"se"}]`
	}
	return fmt.Sprintf(`{"number":%d,"state":%q,"state_reason":%q,"html_url":"u%d","repository_url":"https://api.github.com/repos/o/r","labels":%s}`, n, state, reason, n, ls)
}

// ready5 is the fleet's ready work, in a manifest as all work is: #5, a
// manifest, holding its ready leaf #1, which newWorld lists with it.
var ready5 = item(5, 1, ManifestLabel)

func newWorld(t *testing.T, items []string, claimed ...int) *world {
	t.Helper()
	answers := map[string]string{"repos/o/r/issues/100": `{"number":100,"state":"closed"}`}
	if slices.Contains(items, ready5) {
		items = append(items, item(1, 0))
		answers[subsPath(5)] = "[" + item(1, 0) + "]"
	}
	answers[listPath] = "[" + strings.Join(items, ",") + "]"
	w := &world{t: t, Fake: recorded(t, answers)}
	var refs []string
	for _, n := range claimed {
		refs = append(refs, fmt.Sprintf(`{"ref":"refs/heads/issue-%d","object":{"sha":"c%d"}}`, n, n))
		w.ahead(n, 1)
	}
	w.set(refsPath, "["+strings.Join(refs, ",")+"]")
	return w
}

// in5 files the leaves ns into the manifest #5, beside its leaf #1.
func (w *world) in5(ns ...int) {
	subs := []string{item(1, 0)}
	for _, n := range ns {
		subs = append(subs, item(n, 0))
	}
	w.set(subsPath(5), "["+strings.Join(subs, ",")+"]")
}

// ahead records how many commits issue-n's branch has that main lacks.
func (w *world) ahead(n, by int) {
	w.set(fmt.Sprintf("repos/o/r/compare/main...c%d?per_page=1", n), fmt.Sprintf(`{"ahead_by":%d}`, by))
}

// pushed records the last push to issue-n's branch.
func (w *world) pushed(n int, at string) {
	w.set(fmt.Sprintf("repos/o/r/activity?ref=refs/heads/issue-%d&per_page=1", n), fmt.Sprintf(`[{"timestamp":%q,"activity_type":"push"}]`, at))
}

// pr records issue-n's open PR n*10 at head e<n>: whether it merges, its
// auto-merge, and its check runs as name:conclusion, or name: still running.
func (w *world) pr(n int, mergeable, state string, autoMerge bool, runs ...string) {
	am := "null"
	if autoMerge {
		am = `{"merge_method":"squash"}`
	}
	p := fmt.Sprintf(`{"number":%d,"html_url":"p%d","node_id":"N%d","mergeable":%s,"mergeable_state":%q,"auto_merge":%s,"head":{"ref":"issue-%d","sha":"e%d"},"base":{"ref":"main"}}`,
		n*10, n*10, n*10, mergeable, state, am, n, n)
	w.set(openPullsPath, "["+p+"]")
	var rs []string
	for _, r := range runs {
		name, conclusion, _ := strings.Cut(r, ":")
		status := "completed"
		if conclusion == "" {
			status = "in_progress"
		}
		rs = append(rs, fmt.Sprintf(`{"name":%q,"status":%q,"conclusion":%q}`, name, status, conclusion))
	}
	w.set(fmt.Sprintf("repos/o/r/commits/e%d/check-runs?per_page=100", n), `{"check_runs":[`+strings.Join(rs, ",")+`]}`)
}

// closedPRs records issue-n's closed PRs.
func (w *world) closedPRs(n int, prs string) {
	w.set(fmt.Sprintf("repos/o/r/pulls?head=o:issue-%d&base=main&state=closed&per_page=100", n), prs)
}

// get reads path from the fake GitHub, as text.
func get(t *testing.T, gh github.GitHub, path string) string {
	t.Helper()
	out, err := gh.Get(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(out)
}

func (w *world) check() []Finding {
	w.t.Helper()
	got, err := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Check()
	if err != nil {
		w.t.Fatal(err)
	}
	return got
}

// only checks that the check found exactly one finding, of this kind on
// this issue, and answers it.
func only(t *testing.T, got []Finding, kind string, n int) Finding {
	t.Helper()
	if len(got) != 1 || got[0].Kind != kind || got[0].Issue != n {
		t.Fatalf("want one %s on #%d, got %+v", kind, n, got)
	}
	return got[0]
}

func TestAFleetWithNothingBrokenIsHealthy(t *testing.T) {
	t.Parallel()
	// #5 is ready, #6 waits on #5, #7 is claimed and its PR is green, mergeable,
	// with auto-merge on and a push half an hour ago.
	w := newWorld(t, []string{ready5, item(6, 0), item(7, 0)}, 7)
	w.set(links(6), "["+dep(5, "open", "", true)+"]")
	w.pushed(7, recent)
	w.pr(7, "true", "clean", true, "check:success")
	if got := w.check(); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
	// Running CI, and a fresh claim with no PR yet, are moving too.
	w.pr(7, "true", "unstable", true, "check:")
	if got := w.check(); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
	w = newWorld(t, []string{ready5, item(7, 0)}, 7)
	w.pushed(7, recent)
	if got := w.check(); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
}

func TestAConflictedPRIsFoundAndTakenOver(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5, item(7, 0)}, 7)
	w.pushed(7, recent)
	w.pr(7, "false", "dirty", true)
	f := only(t, w.check(), ConflictedPR, 7)
	if f.PR != 70 || f.What != "PR #70 conflicts with main" || f.Remedy != "se issue pull --take 7, merge origin/main into issue-7, make it green, se issue land" {
		t.Fatalf("%+v", f)
	}
	// A takeover in flight at this head is left to its box; one an hour old
	// at the same head is stuck again.
	w.said(7, "<!-- se:takeover 1 -->\n<!-- se:takeover-head e7 -->", noon.Add(-10*time.Minute))
	if got := w.check(); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
	w.said(7, "<!-- se:takeover 1 -->\n<!-- se:takeover-head e7 -->", noon.Add(-2*time.Hour))
	only(t, w.check(), ConflictedPR, 7)
}

func TestARedPRIsFoundOnceItIsQuiet(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5, item(7, 0)}, 7)
	w.pr(7, "true", "unstable", true, "check:failure", "lint:success")
	w.pushed(7, recent)
	if got := w.check(); len(got) != 0 {
		t.Fatalf("a box may be fixing it: %+v", got)
	}
	w.pushed(7, quiet)
	f := only(t, w.check(), RedPR, 7)
	if f.What != "PR #70 fails check on its latest commit, and no push since 2026-10-13T09:00:00Z" || !strings.HasPrefix(f.Remedy, "se issue pull --take 7") {
		t.Fatalf("%+v", f)
	}
}

// The lease and se fleet check read one rule for a quiet claim: a takeover a
// minute ago keeps it moving for both, however old its last push; no push and
// no takeover past the lease is quiet to both.
func TestTheLeaseAndTheFleetCheckAgreeWhenAClaimIsQuiet(t *testing.T) {
	t.Parallel()
	stale := noon.Add(-Lease - time.Hour).Format(time.RFC3339)
	for _, c := range []struct {
		name   string
		pushed string
		taken  bool
		quiet  bool
	}{
		{"taken over a minute ago", `[{"timestamp":"` + stale + `","activity_type":"push"}]`, true, false},
		{"no push and no takeover", `[]`, false, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			t.Parallel()
			w := newWorld(t, []string{ready5, item(7, 0)}, 7)
			w.set("repos/o/r/activity?ref=refs/heads/issue-7&per_page=1", c.pushed)
			w.pr(7, "true", "unstable", true, "check:failure")
			if c.taken {
				w.said(7, "<!-- se:takeover 1 -->", noon.Add(-time.Minute))
			}
			s := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}
			st := Status{Issue: Issue{Number: 7}}
			if err := s.lease(&st); err != nil {
				t.Fatal(err)
			}
			if st.Stuck != c.quiet {
				t.Fatalf("the lease says stuck %v, want %v", st.Stuck, c.quiet)
			}
			if got := w.check(); (len(got) > 0) != c.quiet {
				t.Fatalf("se fleet check finds %+v, want quiet %v", got, c.quiet)
			}
		})
	}
}

func TestAGreenPRWithAutoMergeOffIsFoundAtOnce(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5, item(7, 0)}, 7)
	w.pr(7, "true", "clean", false, "check:success")
	w.pushed(7, recent)
	f := only(t, w.check(), GreenUnmerged, 7)
	if f.Remedy != "se fleet fix turns auto-merge on" {
		t.Fatalf("%+v", f)
	}
	// With auto-merge on, it sits unmerged only once it is quiet.
	w.pr(7, "true", "blocked", true, "check:success")
	if got := w.check(); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
	w.pushed(7, quiet)
	if f := only(t, w.check(), GreenUnmerged, 7); f.Remedy != "se fleet fix reports it as an se-person issue" {
		t.Fatalf("%+v", f)
	}
}

func TestAClaimWithNoPRIsFoundOnceItIsQuiet(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5, item(7, 0)}, 7)
	w.closedPRs(7, `[]`)
	w.pushed(7, quiet)
	f := only(t, w.check(), NoPR, 7)
	if f.What != "issue-7 has no PR, and no push since 2026-10-13T09:00:00Z" {
		t.Fatalf("%+v", f)
	}
	// A PR closed unmerged leaves the claim behind.
	w.closedPRs(7, `[{"number":70,"merged_at":null}]`)
	if f := only(t, w.check(), LeftoverClaim, 7); f.What != "issue-7 claims #7, but its PR #70 was closed unmerged" {
		t.Fatalf("%+v", f)
	}
}

func TestABranchOfAClosedIssueIsALeftoverClaim(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5}, 19)
	w.set("repos/o/r/issues/19", `{"number":19,"state":"closed","state_reason":"not_planned","closed_at":"2026-10-13T11:00:00Z"}`)
	f := only(t, w.check(), LeftoverClaim, 19)
	if f.What != "issue-19 claims #19, which is closed (not planned)" ||
		f.Remedy != "the prune workflow deletes issue-19; se fleet fix reports it only if it is still there a day after #19 closed" {
		t.Fatalf("%+v", f)
	}
	// Within a day of the close, se fleet fix leaves it to the prune
	// workflow and writes nothing.
	s := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}
	done := s.Fix(t.TempDir(), []Finding{f})
	if done[0].Did != "left to the prune workflow until a day after #19 closed" || len(w.Writes()) != 0 {
		t.Fatalf("%+v, writes %q", done, w.Writes())
	}
	// A day later the workflow failed: it becomes an se issue.
	w.set("repos/o/r/issues/19", `{"number":19,"state":"closed","state_reason":"not_planned","closed_at":"2026-10-12T11:00:00Z"}`)
	done = s.Fix(t.TempDir(), w.check())
	// It goes into a new misc manifest, #101.
	if done[0].Did != "reported it as #102" || !done[0].Ready ||
		done[0].What != "issue-19 claims #19, which is closed (not planned), and is still there a day after it closed: the prune workflow did not delete it" {
		t.Fatalf("%+v", done)
	}
	// With an open PR, the workflow leaves it, so se fleet fix reports it.
	w.set(allPullsPath, `[{"number":90,"head":{"ref":"issue-19","sha":"c19"}}]`)
	if f := only(t, w.check(), LeftoverClaim, 19); f.Remedy != "se fleet fix reports it as an se issue" {
		t.Fatalf("%+v", f)
	}
}

func TestFleetFixDeletesALeftoverBranchMainHoldsWhole(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5}, 19)
	w.set("repos/o/r/issues/19", `{"number":19,"state":"open"}`)
	w.ahead(19, 0)
	f := only(t, w.check(), LeftoverClaim, 19)
	if f.What != "issue-19 claims #19, which is not labelled se, and main holds all its commits" || f.Remedy != "se fleet fix deletes issue-19: main holds all its commits" {
		t.Fatalf("%+v", f)
	}
	// The branch goes by a git push from the checkout, never the REST API,
	// which the boxes' proxy refuses.
	origin, a, _ := boxes(t)
	run(t, a, "push", "-q", "origin", "main:issue-19")
	done := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Fix(a, []Finding{f})
	if done[0].Did != "deleted issue-19 at c19, which main holds whole" || done[0].Made != 0 || done[0].Failed != "" {
		t.Fatalf("%+v", done)
	}
	if got := run(t, origin, "branch", "--list", "issue-19"); got != "" {
		t.Fatalf("origin still has %q", got)
	}
	if got := w.Writes(); !reflect.DeepEqual(got, []string{"POST repos/o/r/issues/19/comments"}) {
		t.Fatalf("writes %q", got)
	}
	if c := commentsAt(t, w, 19); len(c) != 1 || !strings.Contains(c[0].Body, "<!-- se:fleet leftover-branch 0 -->") {
		t.Fatalf("#19 has no record: %+v", c)
	}
}

func TestAFailedRemedyDoesNotStopTheOnesAfterIt(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5, item(8, 0)}, 19)
	w.in5(8)
	w.set("repos/o/r/issues/19", `{"number":19,"state":"open"}`)
	w.ahead(19, 0)
	w.set(links(8), "["+dep(3, "closed", "not_planned", true)+"]")
	// The workspace is no checkout, so the push that deletes issue-19 fails.
	done := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Fix(t.TempDir(), w.check())
	var dids []string
	for _, d := range done {
		dids = append(dids, fmt.Sprintf("%s #%d: %s", d.Kind, d.Issue, d.Did))
	}
	if len(done) != 2 || !strings.HasPrefix(done[0].Did, "failed: deleting issue-19: git push -q origin --delete issue-19: ") || done[0].Failed == "" ||
		dids[1] != "impossible block #8: reported it as #102" || done[1].Failed != "" {
		t.Fatalf("got\n%s", strings.Join(dids, "\n"))
	}
	if c19, c8 := commentsAt(t, w, 19), commentsAt(t, w, 8); len(c19) != 0 || len(c8) != 1 {
		t.Fatalf("records: #19 %+v, #8 %+v", c19, c8)
	}
}

func TestImpossibleBlocksAreFound(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5, item(8, 0), item(9, 0), item(10, 0), item(11, 0), item(12, 0)})
	w.in5(8)
	w.set(links(8), "["+dep(3, "closed", "not_planned", true)+"]")
	w.set(links(9), "["+dep(4, "open", "", false)+"]")
	w.set(links(10), "["+dep(11, "open", "", true)+"]")
	w.set(links(11), "["+dep(12, "open", "", true)+"]")
	w.set(links(12), "["+dep(10, "open", "", true)+"]")
	got := w.check()
	var whats []string
	for _, f := range got {
		if f.Kind != ImpossibleBlock {
			t.Errorf("%+v", f)
		}
		whats = append(whats, fmt.Sprintf("#%d %s: %s", f.Issue, f.What, f.Remedy))
	}
	want := []string{
		"#8 #8 is blocked by #3, which was closed as not planned: se fleet fix reports it as an se issue",
		"#9 #9 is blocked by u4, which is no se issue, so no box moves it: se fleet fix reports it as an se-person issue",
		"#10 a cycle of blocks: #10 is blocked by #11 is blocked by #12 is blocked by #10: se fleet fix reports it as an se-person issue",
	}
	if !reflect.DeepEqual(whats, want) {
		t.Fatalf("got\n%s", strings.Join(whats, "\n"))
	}
}

func TestAnIssueWaitingOnAPersonIsReportedWithWhatItHoldsUp(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5, item(12, 0, PersonLabel), item(13, 0)})
	w.set(links(13), "["+dep(12, "open", "", true)+"]")
	f := only(t, w.check(), WaitingOnPerson, 12)
	if !reflect.DeepEqual(f.Holds, []int{13}) || f.What != "#12 waits for a person (se-person), holding up #13" || f.Remedy != "none: it waits for a person" {
		t.Fatalf("%+v", f)
	}
}

// Recorded from mb-89/SE on 13 October: #17, the guard against stuck work,
// is claimed, and its PR #170 conflicts with main; its takeover, at that very
// head, is hours old. #38 waits on #17, #39 on #38, the parent #51 on #38,
// and so does its sub-issue #52. Nothing is ready, and every box left.
func TestThirteenOctoberTheGuardBlockedByWhatItGuardsIsTheStalledRoot(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{item(17, 0, FinalLabel), item(38, 0), item(39, 0), item(51, 1), item(52, 0)}, 17)
	w.set(subsPath(51), `[`+item(52, 0)+`]`)
	w.set(links(38), "["+dep(17, "open", "", true)+"]")
	w.set(links(39), "["+dep(38, "open", "", true)+"]")
	w.set(links(51), "["+dep(38, "open", "", true)+"]")
	w.pushed(17, quiet)
	w.pr(17, "false", "dirty", true)
	w.said(17, "<!-- se:takeover 1 -->\n<!-- se:takeover-head e17 -->", noon.Add(-3*time.Hour))
	f := only(t, w.check(), StalledRoot, 17)
	if f.Cause != ConflictedPR || !reflect.DeepEqual(f.Holds, []int{38, 39, 51, 52}) ||
		f.What != "nothing is ready, and #38, #39, #51, #52 wait on #17: PR #170 conflicts with main" ||
		f.Remedy != "se issue pull --take 17, merge origin/main into issue-17, make it green, se issue land" {
		t.Fatalf("%+v", f)
	}
	// Its remedy, run: a conflict is no failure, so #17, final or not, is
	// taken over again, and nothing waits on a person.
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Take(claimedAt(t, 17), 17)
	if err != nil || !ok || took.Takeover == nil || took.Takeover.Count != 2 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if by := linksOf(t, w.Fake, links(17)); len(by) != 0 || !labelled(t, w, 17, FinalLabel) {
		t.Fatalf("#17 is blocked by %v; writes %q", by, w.Writes())
	}
}

// Recorded from mb-89/SE on 14 October: #60, final, was taken over as stuck
// at 08:01:45, which recorded a comment and no push; at 08:03:42 the
// coordination remedy found it final and quiet and held it, and its box
// landed PR #127 anyway. A takeover a minute old renews the claim as a push
// does: neither se fleet check nor se issue next --take N holds it.
func TestAFinalClaimTakenOverAMinuteAgoIsNotHeld(t *testing.T) {
	t.Parallel()
	for name, pr := range map[string]func(w *world){
		"no PR":  func(w *world) { w.closedPRs(7, `[]`) },
		"red PR": func(w *world) { w.pr(7, "true", "clean", true, "check:failure") },
	} {
		w := newWorld(t, []string{item(5, 0), item(7, 0, FinalLabel)}, 7)
		pr(w)
		w.pushed(7, quiet)
		w.said(7, "<!-- se:takeover 1 -->\nTaken over: nothing was pushed to issue-7.", noon.Add(-time.Minute))
		for _, f := range w.check() {
			if f.Issue == 7 {
				t.Errorf("%s: se fleet check finds %+v", name, f)
			}
		}
		_, _, err := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Take(t.TempDir(), 7)
		if err == nil || !strings.Contains(err.Error(), "nothing about it is stuck") {
			t.Errorf("%s: %v", name, err)
		}
		if c := commentsAt(t, w, 7); len(c) != 1 || len(w.Writes()) != 0 {
			t.Errorf("%s: #7 was held: %+v, writes %q", name, c, w.Writes())
		}
	}
}

func TestAStuckClaimNamedWithTakeIsTakenOver(t *testing.T) {
	t.Parallel()
	a := claimed7(t)
	w := newWorld(t, []string{ready5, item(7, 0)}, 7)
	w.closedPRs(7, `[]`)
	w.pushed(7, quiet)
	took, ok, err := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Take(a, 7)
	if err != nil || !ok || took.Takeover == nil || *took.Takeover != (Takeover{Count: 1, Stale: "issue-7 has no PR, and no push since 2026-10-13T09:00:00Z"}) {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if got := run(t, a, "log", "-1", "--format=%s"); got != "work on 7" {
		t.Fatalf("issue-7 is not checked out as it stands: %s", got)
	}
	if c := commentsAt(t, w, 7); len(c) != 1 || !strings.Contains(c[0].Body, "<!-- se:takeover 1 -->") || !strings.Contains(c[0].Body, "<!-- se:takeover-head c7 -->") {
		t.Fatalf("%+v", c)
	}
	// The takeover makes #7 final: stuck again, it goes to a person.
	if !labelled(t, w, 7, FinalLabel) {
		t.Fatalf("writes %q", w.Writes())
	}
	// Moving work is no takeover.
	w.pushed(7, recent)
	w.set("repos/o/r/issues/7/comments", `[]`)
	if _, _, err := (Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}).Take(t.TempDir(), 7); err == nil || !strings.Contains(err.Error(), "nothing about it is stuck") {
		t.Fatalf("%v", err)
	}
}

func TestFleetFixAppliesEachRemedyAndRecordsIt(t *testing.T) {
	t.Parallel()
	w := newWorld(t, []string{ready5, item(7, 0), item(8, 0), item(9, 0)}, 7, 19)
	w.in5(8)
	// A review is still required on #70, so auto-merge waits for it.
	w.pr(7, "true", "blocked", false, "check:success")
	w.pushed(7, recent)
	w.set("repos/o/r/issues/19", `{"number":19,"state":"closed","state_reason":"not_planned","closed_at":"2026-10-11T12:00:00Z"}`)
	w.set(links(8), "["+dep(3, "closed", "not_planned", true)+"]")
	w.set(links(9), "["+dep(4, "open", "", false)+"]")
	s := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}
	found := w.check()
	done := s.Fix(t.TempDir(), found)
	var dids []string
	for _, d := range done {
		dids = append(dids, fmt.Sprintf("%s #%d: %s", d.Kind, d.Issue, d.Did))
	}
	want := []string{
		"green but unmerged #7: turned auto-merge on for PR #70",
		"leftover claim #19: reported it as #102",
		"impossible block #8: reported it as #103",
		"impossible block #9: reported it to a person as #104",
	}
	if !reflect.DeepEqual(dids, want) {
		t.Fatalf("got\n%s", strings.Join(dids, "\n"))
	}
	// The reports go into one misc manifest, #101, which the first opened;
	// the issue for a person stands at the top.
	if subs := get(t, w, "repos/o/r/issues/101/sub_issues"); !strings.Contains(subs, `"number":102`) || !strings.Contains(subs, `"number":103`) || strings.Contains(subs, `"number":104`) {
		t.Fatalf("the misc manifest holds %s", subs)
	}
	if !done[1].Ready || done[3].Ready || !strings.Contains(get(t, w, "repos/o/r/issues/104"), `"assignees":[{"login":"o"}]`) ||
		!strings.Contains(get(t, w, "repos/o/r/pulls/70"), `"auto_merge":{"merge_method":"squash"}`) {
		t.Fatalf("%+v, writes %q", done, w.Writes())
	}
	for _, n := range []int{7, 19, 8, 9} {
		if c := commentsAt(t, w, n); len(c) != 1 || !strings.Contains(c[0].Body, "<!-- se:fleet ") {
			t.Errorf("#%d has no record: %+v", n, c)
		}
	}
	// Run again with the same findings: the reported ones are still open and
	// are left as they are; the green PR is back after its fix, as GitHub
	// turned its auto-merge off again, so it goes to a person.
	w.pr(7, "true", "blocked", false, "check:success")
	fixed := len(w.Writes())
	done = s.Fix(t.TempDir(), w.check())
	dids = nil
	for _, d := range done {
		dids = append(dids, fmt.Sprintf("%s #%d: %s", d.Kind, d.Issue, d.Did))
	}
	want = []string{
		"green but unmerged #7: it is back after a fix, so it went to a person as #105",
		"leftover claim #19: reported already as #102, still open",
		"impossible block #8: reported already as #103, still open",
		"impossible block #9: reported already as #104, still open",
		// #104 is for a person, and waits on them.
		"waiting on a person #104: reported; it waits for a person",
	}
	if !reflect.DeepEqual(dids, want) {
		t.Fatalf("got\n%s", strings.Join(dids, "\n"))
	}
	for _, x := range w.Writes()[fixed:] {
		if x == "POST graphql" {
			t.Fatalf("auto-merge was turned on again: %q", w.Writes()[fixed:])
		}
	}
	if !labelled(t, w, 105, PersonLabel) || !strings.Contains(get(t, w, "repos/o/r/issues/105"), `"assignees":[{"login":"o"}]`) {
		t.Fatalf("#105 is not for a person: %s", get(t, w, "repos/o/r/issues/105"))
	}
	// A takeover is left to the box; a person is only reported.
	x := s.Fix(t.TempDir(), []Finding{{Kind: ConflictedPR, Issue: 7}, {Kind: WaitingOnPerson, Issue: 12}})
	if !x[0].Take || x[1].Take || x[1].Did != "reported; it waits for a person" {
		t.Fatalf("%+v", x)
	}
}

// Recorded from mb-89/SE on 14 October: #60, a sub-issue of #59, is claimed
// and quiet, and #117, for a person, blocks it, directly or through #59. #44
// waits on #60. Nothing about #60 is a box's to fix: the one finding is #117,
// and it holds #60's dependants.
func TestFourteenOctoberAClaimAPersonBlocksIsNoStalledRoot(t *testing.T) {
	t.Parallel()
	for _, blocked := range []int{60, 59} {
		w := newWorld(t, []string{item(44, 0), item(59, 1), item(60, 0), item(117, 0, PersonLabel)}, 60)
		w.set(subsPath(59), `[`+item(60, 0)+`]`)
		w.set(links(blocked), "["+dep(117, "open", "", true)+"]")
		w.set(links(44), "["+dep(60, "open", "", true)+"]")
		w.pushed(60, quiet)
		f := only(t, w.check(), WaitingOnPerson, 117)
		if !reflect.DeepEqual(f.Holds, []int{44, 59, 60}) {
			t.Fatalf("blocked through #%d: %+v", blocked, f)
		}
	}
}

// Every takeover remedy se fleet check names for a stuck sub-issue leaf runs:
// within the lease, and past it.
func TestTheTakeoverRemedyOfAStuckSubIssueLeafRuns(t *testing.T) {
	t.Parallel()
	for _, at := range []string{quiet, "2026-10-13T07:00:00Z"} {
		a := claimed7(t)
		w := newWorld(t, []string{item(5, 1), item(7, 0)}, 7)
		w.set(subsPath(5), `[`+item(7, 0)+`]`)
		w.closedPRs(7, `[]`)
		w.pushed(7, at)
		got := w.check()
		if len(got) != 1 || got[0].Issue != 7 || got[0].cause() != NoPR {
			t.Fatalf("pushed at %s: %+v", at, got)
		}
		f := got[0]
		var n int
		if _, err := fmt.Sscanf(f.Remedy, "se issue pull --take %d,", &n); err != nil || n != 7 {
			t.Fatalf("pushed at %s: remedy %q", at, f.Remedy)
		}
		took, ok, err := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Take(a, n)
		if err != nil || !ok || took.Number != 7 || took.Takeover == nil {
			t.Fatalf("pushed at %s: took %+v %v %v", at, took, ok, err)
		}
		if got := run(t, a, "log", "-1", "--format=%s"); got != "work on 7" {
			t.Fatalf("pushed at %s: issue-7 is not checked out as it stands: %s", at, got)
		}
	}
}

// An se built before manifests files bare issues, which no box takes: se
// fleet check finds each open one at the top that nothing holds or claims,
// and se fleet fix files it into the open misc manifest, once.
func TestABareIssueIsFiledIntoTheMiscManifest(t *testing.T) {
	t.Parallel()
	// #20 is bare. #7 is bare but claimed, #25 bare but blocked; #21, #22
	// and #24 stand at the top by themselves (a retro, an overhaul, an empty
	// manifest), and #23 is a sub-issue of #5.
	w := newWorld(t, []string{ready5, item(7, 0), item(20, 0), item(21, 0, RetroLabel), item(22, 0, OverhaulLabel), item(23, 0), item(24, 0, ManifestLabel), item(25, 0)}, 7)
	w.in5(23)
	w.pushed(7, recent)
	w.set(links(25), "["+dep(20, "open", "", true)+"]")
	f := only(t, w.check(), BareIssue, 20)
	if f.What != "#20 stands in no manifest, and boxes take only manifests" || f.Remedy != "se fleet fix files it into the open misc manifest" {
		t.Fatalf("%+v", f)
	}
	// No misc manifest is open: the fix opens #101 and files #20 into it.
	s := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}
	done := s.Fix(t.TempDir(), []Finding{f})
	if len(done) != 1 || done[0].Did != "filed it into misc manifest #101" || done[0].Failed != "" || done[0].Made != 0 {
		t.Fatalf("%+v", done)
	}
	if top, err := s.manifestOf(20); err != nil || top != 101 || !labelled(t, w, 101, MiscLabel) {
		t.Fatalf("#20 is in #%d (%v)", top, err)
	}
	if c := commentsAt(t, w, 20); len(c) != 1 || !strings.Contains(c[0].Body, "se fleet fix filed it into misc manifest #101.") || !strings.Contains(c[0].Body, "<!-- se:fleet bare-issue 0 -->") {
		t.Fatalf("the fix is not recorded on #20: %+v", c)
	}
	// Found bare again after its fix, it goes to a person.
	done = s.Fix(t.TempDir(), []Finding{f})
	if len(done) != 1 || done[0].Did != "it is back after a fix, so it went to a person as #102" || !labelled(t, w, 102, PersonLabel) {
		t.Fatalf("%+v", done)
	}

	// An open misc manifest takes it, and no other opens.
	w = newWorld(t, []string{ready5, item(20, 0)})
	s.GitHub = w
	misc, err := s.FileInto()
	if err != nil {
		t.Fatal(err)
	}
	done = s.Fix(t.TempDir(), w.check())
	if len(done) != 1 || done[0].Did != fmt.Sprintf("filed it into misc manifest #%d", misc) {
		t.Fatalf("%+v", done)
	}
	if top, err := s.manifestOf(20); err != nil || top != misc {
		t.Fatalf("#20 is in #%d (%v), want #%d", top, err, misc)
	}
}
