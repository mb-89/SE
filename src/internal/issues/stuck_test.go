// Internal test package: it uses the unexported comment type and drives stake.
package issues

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"
)

// github answers gh api calls like recorded, and keeps each issue's comments:
// a comment posted is read back by the next read. It records every write.
// Links not recorded answer none.
type github struct {
	t        *testing.T
	answers  map[string]string
	comments map[int][]comment
	nextID   int64
	writes   [][]string
}

func newGithub(t *testing.T, answers map[string]string) *github {
	return &github{t: t, answers: answers, comments: map[int][]comment{}, nextID: 1000}
}

// say records a comment on issue n made before the test's now.
func (g *github) say(n int, body string) {
	g.nextID++
	g.comments[n] = append(g.comments[n], comment{ID: g.nextID, Body: body, Created: now.Add(-5 * time.Hour)})
}

func (g *github) gh(args ...string) ([]byte, error) {
	g.t.Helper()
	path := args[len(args)-1]
	var n int
	if _, err := fmt.Sscanf(path, "repos/o/r/issues/%d/comments", &n); err == nil {
		if args[1] == "-X" {
			g.writes = append(g.writes, args)
			g.nextID++
			c := comment{ID: g.nextID, Body: strings.TrimPrefix(args[len(args)-2], "body="), Created: now}
			g.comments[n] = append(g.comments[n], c)
			return json.Marshal(c)
		}
		list := g.comments[n]
		if list == nil {
			list = []comment{}
		}
		return json.Marshal(list)
	}
	if args[1] == "-X" {
		g.writes = append(g.writes, args)
		// The issue for a person the sweep mints.
		if args[2] == "POST" && path == "repos/o/r/issues" {
			return []byte(`{"number":101,"id":1010,"html_url":"u101"}`), nil
		}
		return []byte(`{}`), nil
	}
	a, ok := g.answers[path]
	if !ok && strings.HasSuffix(path, "/dependencies/blocked_by?per_page=100") {
		// An issue whose links are not recorded is blocked by nothing.
		a, ok = `[]`, true
	}
	if !ok {
		g.t.Fatalf("gh api %s was not recorded", path)
	}
	return []byte(a), nil
}

func (g *github) source() Source { return Source{Repo: repo, GH: g.gh, Clock: atNow()} }

func refs(ns ...int) string {
	var out []string
	for _, n := range ns {
		out = append(out, fmt.Sprintf(`{"ref":"refs/heads/issue-%d"}`, n))
	}
	return "[" + strings.Join(out, ",") + "]"
}

func TestAFreshClaimIsNotStuckAndAStaleOneIs(t *testing.T) {
	g := newGithub(t, map[string]string{
		listPath:    list(node(1, 0), node(2, 0), node(3, 0), node(4, 0)),
		refsPath:    refs(1, 2, 3, 4),
		activity(1): pushed(fresh),
		activity(2): pushed(stale),
		// A takeover renews the lease, however old the last push.
		activity(3): pushed(stale),
		// A branch GitHub keeps no push record of is stuck.
		activity(4): `[]`,
	})
	g.comments[3] = []comment{{ID: 1, Body: "<!-- se:takeover 1 -->\nTaken over", Created: now.Add(-time.Hour)}}
	all, err := g.source().Survey()
	if err != nil {
		t.Fatal(err)
	}
	got := map[int]bool{}
	for _, st := range all {
		got[st.Number] = st.Stuck
	}
	if want := map[int]bool{1: false, 2: true, 3: false, 4: true}; !reflect.DeepEqual(got, want) {
		t.Fatalf("stuck %v, want %v", got, want)
	}
	if all[0].Why != "claimed by issue-1" || all[1].Why != "claimed by issue-2, stuck: nothing was pushed to issue-2 since 2026-10-13T08:00:00Z" {
		t.Fatalf("%q %q", all[0].Why, all[1].Why)
	}
	if all[2].Takeovers != 1 || all[2].Takeover != nil || all[1].Takeover == nil {
		t.Fatalf("%+v", all)
	}
	if len(g.writes) != 0 {
		t.Fatalf("writes %q", g.writes)
	}
}

func TestATakeoverComesBeforeNewWorkAndContinuesTheBranch(t *testing.T) {
	origin, a, b := boxes(t)
	// a claimed #5, pushed some work, and stalled.
	if ok, err := Claim(a, 5); err != nil || !ok {
		t.Fatalf("claim: %v %v", ok, err)
	}
	run(t, a, "commit", "-q", "--allow-empty", "-m", "half done")
	run(t, a, "push", "-q", "origin", "issue-5")
	g := newGithub(t, map[string]string{
		listPath:    list(node(3, 0), node(5, 0)),
		refsPath:    refs(5),
		activity(5): pushed(stale),
		// #5 has no PR yet, so none conflicts.
		openPullsPath: `[]`,
	})
	s := g.source()
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 5 || next.Takeover == nil {
		t.Fatalf("next = %+v %v %v", next, ok, err)
	}
	took, ok, err := s.Take(b, 0)
	if err != nil || !ok || took.Number != 5 || took.Takeover == nil {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if got := run(t, b, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-5" {
		t.Fatalf("b is on %s", got)
	}
	if got, want := run(t, b, "rev-parse", "HEAD"), run(t, origin, "rev-parse", "issue-5"); got != want {
		t.Fatalf("b is at %s, not the branch's %s", got, want)
	}
	if got := run(t, b, "rev-parse", "--abbrev-ref", "@{upstream}"); got != "origin/issue-5" {
		t.Fatalf("b tracks %s", got)
	}
	// The takeover is recorded, and makes #5 final.
	if len(g.writes) != 2 || !strings.Contains(strings.Join(g.writes[0], " "), "<!-- se:takeover 1 -->") ||
		!reflect.DeepEqual(g.writes[1], []string{"api", "-X", "POST", "-f", "labels[]=se-final", "repos/o/r/issues/5/labels"}) {
		t.Fatalf("writes %q", g.writes)
	}
	// The takeover renewed the lease: the next box finds #5 claimed, not
	// stuck, and takes #3.
	all, err := s.Survey()
	if err != nil || all[1].Stuck || all[1].Takeovers != 1 {
		t.Fatalf("%+v %v", all, err)
	}
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 3 {
		t.Fatalf("next = %+v %v %v", next, ok, err)
	}
}

func TestOfTwoTakeoversTheFirstCommentWins(t *testing.T) {
	_, _, b := boxes(t)
	g := newGithub(t, map[string]string{
		listPath:    list(node(5, 0), node(6, 0)),
		refsPath:    refs(5),
		activity(5): pushed(stale),
	})
	s := g.source()
	all, err := s.Survey()
	if err != nil {
		t.Fatal(err)
	}
	// Another box read the same survey and commented first.
	g.say(5, "<!-- se:takeover 1 -->")
	if ok, err := s.takeOverStuck(b, all[0], true); err != nil || ok {
		t.Fatalf("lost race answered %v %v", ok, err)
	}
	if got := run(t, b, "rev-parse", "--abbrev-ref", "HEAD"); got != "main" {
		t.Fatalf("b moved to %s", got)
	}
	// Two comments for one round count as one takeover.
	if m, err := s.marks(5); err != nil || m.takeovers != 1 {
		t.Fatalf("%+v %v", m, err)
	}
}

func TestAStaleFinalClaimWaitsOnAnIssueForAPerson(t *testing.T) {
	// #5 is se-final: taken over once already, or filed by a review.
	g := newGithub(t, map[string]string{
		listPath:    list(node(5, 0, FinalLabel), node(6, 0)),
		refsPath:    refs(5),
		activity(5): pushed(stale),
	})
	g.say(5, "<!-- se:takeover 1 -->\nTaken over")
	s := g.source()
	var flagged []int
	s.Flagged = func(i Issue, reason string) {
		if !strings.HasPrefix(reason, "Stuck on its final attempt (labelled se-final)") {
			t.Errorf("reason %q", reason)
		}
		flagged = append(flagged, i.Number)
	}
	next, ok, err := s.Next()
	if err != nil || !ok || next.Number != 6 || !reflect.DeepEqual(flagged, []int{5}) {
		t.Fatalf("next %+v %v, flagged %v, %v", next, ok, flagged, err)
	}
	// An issue for a person, #101, is minted and blocks #5; #5 is told so,
	// resumed, and no longer final. #5 itself is never labelled se-person.
	var paths []string
	for _, w := range g.writes {
		paths = append(paths, w[2]+" "+w[len(w)-1])
	}
	want := []string{
		"POST repos/o/r/issues",
		"POST repos/o/r/issues/101/assignees",
		"POST repos/o/r/issues/5/dependencies/blocked_by",
		"POST repos/o/r/issues/5/comments",
		"DELETE repos/o/r/issues/5/labels/se-final",
	}
	if !reflect.DeepEqual(paths, want) {
		t.Fatalf("writes %q", paths)
	}
	if made := strings.Join(g.writes[0], " "); !strings.Contains(made, "title=Decide how #5 goes on: t5") || !strings.Contains(made, "labels[]=se-person") {
		t.Fatalf("minted %q", made)
	}
	if c := g.comments[5][len(g.comments[5])-1].Body; !strings.HasPrefix(c, "<!-- se:person -->\nStuck on its final attempt") || !strings.HasSuffix(c, "<!-- se:resume -->") {
		t.Fatalf("comment %q", c)
	}
	// Blocked by #101, #5's claim waits: it is neither stuck nor taken over.
	g.answers[links(5)] = `[{"number":101,"state":"open"}]`
	if _, _, err := s.Take(t.TempDir(), 5); err == nil || !strings.Contains(err.Error(), "blocked by #101") {
		t.Fatalf("%v", err)
	}
}

func TestIssuesWaitingOnAPersonAndTheirTreesAreNeverOffered(t *testing.T) {
	g := newGithub(t, map[string]string{
		// #10's tree holds #11, which waits on a person, and #12, ready;
		// #20 is blocked by #11, #21 by #20; #30 is free.
		listPath:        list(node(10, 2), node(11, 0, PersonLabel), node(12, 0), node(20, 0), node(21, 0), node(30, 0)),
		refsPath:        refs(10, 11),
		subsPath(10):    subs(11, 12),
		blockedPath(20): subs(11),
		blockedPath(21): subs(20),
	})
	g.say(11, "<!-- se:person -->\nStuck a second time.")
	s := g.source()
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 30 {
		t.Fatalf("next %+v %v %v", next, ok, err)
	}
	for n, why := range map[int]string{10: "#11 waits on a person", 20: "blocked by #11", 21: "blocked by #20"} {
		if _, _, err := s.Take(t.TempDir(), n); err == nil || !strings.Contains(err.Error(), why) {
			t.Errorf("take %d: %v", n, err)
		}
	}
	tr, err := s.In(10)
	if err != nil || len(tr.Ready)+len(tr.Review) != 0 || tr.Why != "#11 waits on a person" {
		t.Fatalf("%+v %v", tr, err)
	}
	if _, _, _, err := s.TakeIn(t.TempDir(), 10, 12); err == nil || !strings.Contains(err.Error(), "#11 waits on a person") {
		t.Fatalf("%v", err)
	}
	// It holds #20 and #21 through their links, and #10 and #12 through its tree.
	waiting, err := s.Waiting()
	if want := []Waiting{{11, "t11", "u11", "Stuck a second time.", 4}}; err != nil || !reflect.DeepEqual(waiting, want) {
		t.Fatalf("waiting %+v %v", waiting, err)
	}
	if len(g.writes) != 0 {
		t.Fatalf("writes %q", g.writes)
	}
}

func TestAStuckLeafInATreeIsTakenOverFirst(t *testing.T) {
	origin, a, b := boxes(t)
	// A sub-agent claimed leaf #11 of #10, pushed some work, and stalled.
	if ok, err := stake(a, 11); err != nil || !ok {
		t.Fatalf("stake: %v %v", ok, err)
	}
	run(t, a, "push", "-q", "origin", "main:issue-10")
	run(t, a, "checkout", "-q", "-b", "w", "origin/issue-11")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "half done")
	run(t, a, "push", "-q", "origin", "w:issue-11")
	g := newGithub(t, map[string]string{
		// #5 stands alone; #10's leaves #11 (stuck) and #12 (ready).
		listPath:     list(node(5, 0), node(10, 2), node(11, 0), node(12, 0)),
		refsPath:     refs(10, 11),
		subsPath(10): subs(11, 12),
		activity(11): pushed(stale),
	})
	s := g.source()
	// Stuck work inside #10 goes before #5, though #5's number is lower.
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 10 {
		t.Fatalf("next %+v %v %v", next, ok, err)
	}
	tr, err := s.In(10)
	if err != nil || !reflect.DeepEqual(numbers(tr.Ready), []int{11, 12}) || tr.Ready[0].Takeover == nil || tr.Ready[1].Takeover != nil {
		t.Fatalf("%+v %v", tr, err)
	}
	took, ok, _, err := s.TakeIn(b, 10, 0)
	if err != nil || !ok || took.Number != 11 || took.Takeover == nil {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	// The branch is fetched as it stands, nothing checked out.
	if got, want := run(t, b, "rev-parse", "origin/issue-11"), run(t, origin, "rev-parse", "issue-11"); got != want {
		t.Fatalf("b has origin/issue-11 at %s, want %s", got, want)
	}
	if got := run(t, b, "rev-parse", "--abbrev-ref", "HEAD"); got != "main" {
		t.Fatalf("b moved to %s", got)
	}
	if len(g.writes) != 2 || !strings.Contains(strings.Join(g.writes[0], " "), "<!-- se:takeover 1 -->") || g.writes[1][4] != "labels[]=se-final" {
		t.Fatalf("writes %q", g.writes)
	}
	// Taken over, #11 is claimed again; #12 is next.
	tr, err = s.In(10)
	if err != nil || !reflect.DeepEqual(numbers(tr.Ready), []int{12}) {
		t.Fatalf("%+v %v", tr, err)
	}
}

func TestAParentsClaimIsNeverStuck(t *testing.T) {
	// No activity is recorded for issue-10: none is asked for.
	g := newGithub(t, map[string]string{
		listPath:     list(node(10, 1), node(11, 0)),
		refsPath:     refs(10),
		subsPath(10): subs(11),
	})
	if next, ok, err := g.source().Next(); err != nil || !ok || next.Number != 10 || next.Takeover != nil {
		t.Fatalf("next %+v %v %v", next, ok, err)
	}
}

func TestResumeResetsTheTakeoverCount(t *testing.T) {
	g := newGithub(t, map[string]string{
		"repos/o/r/issues/5": node(5, 0, FinalLabel, PersonLabel),
		"repos/o/r/issues/6": node(6, 0),
		listPath:             list(node(5, 0)),
		refsPath:             refs(5),
		activity(5):          pushed(stale),
	})
	g.say(5, "<!-- se:takeover 1 -->")
	g.say(5, "<!-- se:person -->\nStuck a second time.")
	s := g.source()
	if _, err := s.Resume(6); err == nil || !strings.Contains(err.Error(), "not an open issue waiting on a person") {
		t.Fatalf("resumed #6: %v", err)
	}
	if i, err := s.Resume(5); err != nil || i.Number != 5 {
		t.Fatalf("%+v %v", i, err)
	}
	// It is no longer final either: it gets one more attempt.
	if len(g.writes) != 3 || g.writes[0][len(g.writes[0])-1] != "repos/o/r/issues/5/comments" ||
		!reflect.DeepEqual(g.writes[1], []string{"api", "-X", "DELETE", "repos/o/r/issues/5/labels/se-final"}) ||
		!reflect.DeepEqual(g.writes[2], []string{"api", "-X", "DELETE", "repos/o/r/issues/5/labels/se-person"}) {
		t.Fatalf("writes %q", g.writes)
	}
	// Back in the queue, still stale: the next take takes it over, round one.
	all, err := s.Survey()
	if err != nil || !all[0].Stuck || all[0].Takeovers != 0 || !all[0].Takeable() {
		t.Fatalf("%+v %v", all, err)
	}
	if len(g.writes) != 3 {
		t.Fatalf("the survey flagged it again: %q", g.writes)
	}
}
