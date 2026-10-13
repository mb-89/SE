package issues

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"
)

// noon is the recorded fleet's clock: pushes at 11:30 are recent, at 9:00 quiet.
var noon = time.Date(2026, 10, 13, 12, 0, 0, 0, time.UTC)

const (
	recent = "2026-10-13T11:30:00Z"
	quiet  = "2026-10-13T09:00:00Z"
)

// world is a recorded repository o/r for se fleet check. Every open issue's
// "blocked by" links are recorded as none unless a test sets them; comments
// are kept per issue, so a record is written and read back, and every write
// is kept.
type world struct {
	t        *testing.T
	answers  map[string]string
	comments map[int][]comment
	writes   [][]string
	made     int
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

func newWorld(t *testing.T, items []string, claimed ...int) *world {
	t.Helper()
	noPause(t)
	w := &world{t: t, comments: map[int][]comment{}, made: 100, answers: map[string]string{
		listPath:      "[" + strings.Join(items, ",") + "]",
		openPullsPath: `[]`,
	}}
	var refs []string
	for _, n := range claimed {
		refs = append(refs, fmt.Sprintf(`{"ref":"refs/heads/issue-%d","object":{"sha":"c%d"}}`, n, n))
	}
	w.answers[refsPath] = "[" + strings.Join(refs, ",") + "]"
	for _, it := range items {
		var i issue
		if err := json.Unmarshal([]byte(it), &i); err != nil {
			t.Fatal(err)
		}
		w.answers[links(i.Number)] = `[]`
	}
	return w
}

// pushed records the last push to issue-n's branch.
func (w *world) pushed(n int, at string) {
	w.answers[fmt.Sprintf("repos/o/r/activity?ref=refs/heads/issue-%d&per_page=1", n)] = fmt.Sprintf(`[{"timestamp":%q,"activity_type":"push"}]`, at)
}

// pr records issue-n's open PR n*10 at head e<n>: whether it merges, its
// auto-merge, and its check runs as name:conclusion, or name: still running.
func (w *world) pr(n int, mergeable, state string, autoMerge bool, runs ...string) {
	am := "null"
	if autoMerge {
		am = `{"merge_method":"squash"}`
	}
	p := fmt.Sprintf(`{"number":%d,"html_url":"p%d","node_id":"N%d","mergeable":%s,"mergeable_state":%q,"auto_merge":%s,"head":{"ref":"issue-%d","sha":"e%d"}}`,
		n*10, n*10, n*10, mergeable, state, am, n, n)
	w.answers[openPullsPath] = "[" + p + "]"
	w.answers[fmt.Sprintf("repos/o/r/pulls/%d", n*10)] = p
	var rs []string
	for _, r := range runs {
		name, conclusion, _ := strings.Cut(r, ":")
		status := "completed"
		if conclusion == "" {
			status = "in_progress"
		}
		rs = append(rs, fmt.Sprintf(`{"name":%q,"status":%q,"conclusion":%q}`, name, status, conclusion))
	}
	w.answers[fmt.Sprintf("repos/o/r/commits/e%d/check-runs?per_page=100", n)] = `{"check_runs":[` + strings.Join(rs, ",") + `]}`
}

// closedPRs records issue-n's closed PRs.
func (w *world) closedPRs(n int, prs string) {
	w.answers[fmt.Sprintf("repos/o/r/pulls?head=o:issue-%d&base=main&state=closed&per_page=100", n)] = prs
}

func (w *world) gh(args ...string) ([]byte, error) {
	w.t.Helper()
	path := args[len(args)-1]
	if args[1] == "-X" || args[1] == "-f" {
		w.writes = append(w.writes, args)
		switch {
		case path == "repos/o/r/issues":
			w.made++
			return []byte(fmt.Sprintf(`{"id":%d,"number":%d,"html_url":"u%d"}`, w.made, w.made, w.made)), nil
		case numbered(path, "repos/o/r/issues/%d/comments") > 0:
			n := numbered(path, "repos/o/r/issues/%d/comments")
			c := comment{ID: int64(1000 + len(w.writes)), Body: strings.TrimPrefix(args[4], "body="), Created: noon}
			w.comments[n] = append(w.comments[n], c)
			return json.Marshal(c)
		}
		return []byte(`{}`), nil
	}
	if n := numbered(path, "repos/o/r/issues/%d/comments?per_page=100"); n > 0 {
		return json.Marshal(append([]comment{}, w.comments[n]...))
	}
	a, ok := w.answers[path]
	if !ok {
		w.t.Fatalf("gh %v was not recorded", args)
	}
	return []byte(a), nil
}

// numbered is the issue number in path, made by format; 0 where format does
// not make path.
func numbered(path, format string) int {
	var n int
	if _, err := fmt.Sscanf(path, format, &n); err != nil || fmt.Sprintf(format, n) != path {
		return 0
	}
	return n
}

func (w *world) check() []Finding {
	w.t.Helper()
	got, err := Source{Repo: repo, GH: w.gh, Now: clock}.Check()
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
	// #5 is ready, #6 waits on #5, #7 is claimed and its PR is green, mergeable,
	// with auto-merge on and a push half an hour ago.
	w := newWorld(t, []string{item(5, 0), item(6, 0), item(7, 0)}, 7)
	w.answers[links(6)] = "[" + dep(5, "open", "", true) + "]"
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
	w.answers[openPullsPath] = `[]`
	w.closedPRs(7, `[]`)
	if got := w.check(); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
}

func TestAConflictedPRIsFoundAndTakenOver(t *testing.T) {
	w := newWorld(t, []string{item(5, 0), item(7, 0)}, 7)
	w.pushed(7, recent)
	w.pr(7, "false", "dirty", true)
	f := only(t, w.check(), ConflictedPR, 7)
	if f.PR != 70 || f.What != "PR #70 conflicts with main" || f.Remedy != "se issue next --take 7, merge origin/main into issue-7, make it green, se issue land" {
		t.Fatalf("%+v", f)
	}
	// A takeover in flight at this head is left to its box; one an hour old
	// at the same head is stuck again.
	w.comments[7] = []comment{{ID: 1, Body: "<!-- se:takeover 1 -->\n<!-- se:takeover-head e7 -->", Created: noon.Add(-10 * time.Minute)}}
	if got := w.check(); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
	w.comments[7][0].Created = noon.Add(-2 * time.Hour)
	only(t, w.check(), ConflictedPR, 7)
}

func TestARedPRIsFoundOnceItIsQuiet(t *testing.T) {
	w := newWorld(t, []string{item(5, 0), item(7, 0)}, 7)
	w.pr(7, "true", "unstable", true, "check:failure", "lint:success")
	w.pushed(7, recent)
	if got := w.check(); len(got) != 0 {
		t.Fatalf("a box may be fixing it: %+v", got)
	}
	w.pushed(7, quiet)
	f := only(t, w.check(), RedPR, 7)
	if f.What != "PR #70 fails check on its latest commit, and no push since 2026-10-13T09:00:00Z" || !strings.HasPrefix(f.Remedy, "se issue next --take 7") {
		t.Fatalf("%+v", f)
	}
}

func TestAGreenPRWithAutoMergeOffIsFoundAtOnce(t *testing.T) {
	w := newWorld(t, []string{item(5, 0), item(7, 0)}, 7)
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
	w := newWorld(t, []string{item(5, 0), item(7, 0)}, 7)
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
	w := newWorld(t, []string{item(5, 0)}, 19)
	w.answers["repos/o/r/issues/19"] = `{"number":19,"state":"closed","state_reason":"not_planned"}`
	f := only(t, w.check(), LeftoverClaim, 19)
	if f.What != "issue-19 claims #19, which is closed (not planned)" || f.Remedy != "se fleet fix reports it as an se issue" {
		t.Fatalf("%+v", f)
	}
}

func TestImpossibleBlocksAreFound(t *testing.T) {
	w := newWorld(t, []string{item(5, 0), item(8, 0), item(9, 0), item(10, 0), item(11, 0), item(12, 0)})
	w.answers[links(8)] = "[" + dep(3, "closed", "not_planned", true) + "]"
	w.answers[links(9)] = "[" + dep(4, "open", "", false) + "]"
	w.answers[links(10)] = "[" + dep(11, "open", "", true) + "]"
	w.answers[links(11)] = "[" + dep(12, "open", "", true) + "]"
	w.answers[links(12)] = "[" + dep(10, "open", "", true) + "]"
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
	w := newWorld(t, []string{item(5, 0), item(12, 0, PersonLabel), item(13, 0)})
	w.answers[links(13)] = "[" + dep(12, "open", "", true) + "]"
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
	w := newWorld(t, []string{item(17, 0), item(38, 0), item(39, 0), item(51, 1), item(52, 0)}, 17)
	w.answers[subsPath(51)] = `[` + item(52, 0) + `]`
	w.answers[links(38)] = "[" + dep(17, "open", "", true) + "]"
	w.answers[links(39)] = "[" + dep(38, "open", "", true) + "]"
	w.answers[links(51)] = "[" + dep(38, "open", "", true) + "]"
	w.pushed(17, quiet)
	w.pr(17, "false", "dirty", true)
	w.comments[17] = []comment{{ID: 1, Body: "<!-- se:takeover 1 -->\n<!-- se:takeover-head e17 -->", Created: noon.Add(-3 * time.Hour)}}
	w.answers["repos/o/r/git/matching-refs/heads/issue-17"] = w.answers[refsPath]
	f := only(t, w.check(), StalledRoot, 17)
	if f.Cause != ConflictedPR || !reflect.DeepEqual(f.Holds, []int{38, 39, 51, 52}) ||
		f.What != "nothing is ready, and #38, #39, #51, #52 wait on #17: PR #170 conflicts with main" ||
		f.Remedy != "se issue next --take 17, merge origin/main into issue-17, make it green, se issue land" {
		t.Fatalf("%+v", f)
	}
	// Its remedy, run: the takeover was made once already, so #17 goes to a
	// person.
	_, _, err := Source{Repo: repo, GH: w.gh, Now: clock}.Take(t.TempDir(), 17)
	if err == nil || !strings.Contains(err.Error(), "went to a person") {
		t.Fatalf("%v", err)
	}
	if !wrote(w, "labels[]=se-person repos/o/r/issues/17/labels") {
		t.Fatalf("writes %q", w.writes)
	}
}

func TestAStuckClaimNamedWithTakeIsTakenOver(t *testing.T) {
	a := claimed7(t)
	w := newWorld(t, []string{item(5, 0), item(7, 0)}, 7)
	w.answers["repos/o/r/git/matching-refs/heads/issue-7"] = w.answers[refsPath]
	w.closedPRs(7, `[]`)
	w.pushed(7, quiet)
	took, ok, err := Source{Repo: repo, GH: w.gh, Now: clock}.Take(a, 7)
	if err != nil || !ok || took.Takeover == nil || *took.Takeover != (Takeover{Count: 1, Stale: "issue-7 has no PR, and no push since 2026-10-13T09:00:00Z"}) {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if got := run(t, a, "log", "-1", "--format=%s"); got != "work on 7" {
		t.Fatalf("issue-7 is not checked out as it stands: %s", got)
	}
	if c := w.comments[7]; len(c) != 1 || !strings.Contains(c[0].Body, "<!-- se:takeover 1 -->") || !strings.Contains(c[0].Body, "<!-- se:takeover-head c7 -->") {
		t.Fatalf("%+v", c)
	}
	// Moving work is no takeover.
	w.pushed(7, recent)
	w.comments[7] = nil
	if _, _, err := (Source{Repo: repo, GH: w.gh, Now: clock}).Take(t.TempDir(), 7); err == nil || !strings.Contains(err.Error(), "nothing about it is stuck") {
		t.Fatalf("%v", err)
	}
}

func wrote(w *world, tail string) bool {
	for _, args := range w.writes {
		if strings.Join(args[len(args)-2:], " ") == tail {
			return true
		}
	}
	return false
}

func TestFleetFixAppliesEachRemedyAndRecordsIt(t *testing.T) {
	w := newWorld(t, []string{item(5, 0), item(7, 0), item(8, 0), item(9, 0)}, 7, 19)
	w.pr(7, "true", "clean", false, "check:success")
	w.pushed(7, recent)
	w.answers["repos/o/r/issues/19"] = `{"number":19,"state":"closed","state_reason":"not_planned"}`
	w.answers[links(8)] = "[" + dep(3, "closed", "not_planned", true) + "]"
	w.answers[links(9)] = "[" + dep(4, "open", "", false) + "]"
	s := Source{Repo: repo, GH: w.gh, Now: clock}
	found := w.check()
	done, err := s.Fix(found)
	if err != nil {
		t.Fatal(err)
	}
	var dids []string
	for _, d := range done {
		dids = append(dids, fmt.Sprintf("%s #%d: %s", d.Kind, d.Issue, d.Did))
	}
	want := []string{
		"green but unmerged #7: turned auto-merge on for PR #70",
		"leftover claim #19: reported it as #101",
		"impossible block #8: reported it as #102",
		"impossible block #9: reported it to a person as #103",
	}
	if !reflect.DeepEqual(dids, want) {
		t.Fatalf("got\n%s", strings.Join(dids, "\n"))
	}
	if !done[1].Ready || done[3].Ready || !wrote(w, "assignees[]=o repos/o/r/issues/103/assignees") || !wrote(w, "id=N70 graphql") {
		t.Fatalf("%+v, writes %q", done, w.writes)
	}
	for _, n := range []int{7, 19, 8, 9} {
		if len(w.comments[n]) != 1 || !strings.Contains(w.comments[n][0].Body, "<!-- se:fleet ") {
			t.Errorf("#%d has no record: %+v", n, w.comments[n])
		}
	}
	// Run again with the same findings: the reported ones are still open and
	// are left as they are; the green PR is back after its fix, so it goes
	// to a person.
	for _, n := range []int{101, 102, 103} {
		w.answers[fmt.Sprintf("repos/o/r/issues/%d", n)] = fmt.Sprintf(`{"number":%d,"state":"open"}`, n)
	}
	w.writes = nil
	done, err = s.Fix(w.check())
	if err != nil {
		t.Fatal(err)
	}
	dids = nil
	for _, d := range done {
		dids = append(dids, fmt.Sprintf("%s #%d: %s", d.Kind, d.Issue, d.Did))
	}
	want = []string{
		"green but unmerged #7: it is back after a fix, so it went to a person as #104",
		"leftover claim #19: reported already as #101, still open",
		"impossible block #8: reported already as #102, still open",
		"impossible block #9: reported already as #103, still open",
	}
	if !reflect.DeepEqual(dids, want) {
		t.Fatalf("got\n%s", strings.Join(dids, "\n"))
	}
	if !wrote(w, "assignees[]=o repos/o/r/issues/104/assignees") || wrote(w, "id=N70 graphql") {
		t.Fatalf("writes %q", w.writes)
	}
	var person bool
	for _, args := range w.writes {
		person = person || (args[len(args)-1] == "repos/o/r/issues" && strings.Contains(strings.Join(args, " "), "labels[]=se-person"))
	}
	if !person {
		t.Fatalf("#104 is not labelled se-person: %q", w.writes)
	}
	// A takeover is left to the box; a person is only reported.
	x, err := s.Fix([]Finding{{Kind: ConflictedPR, Issue: 7}, {Kind: WaitingOnPerson, Issue: 12}})
	if err != nil || !x[0].Take || x[1].Take || x[1].Did != "reported; it waits for a person" {
		t.Fatalf("%+v %v", x, err)
	}
}
