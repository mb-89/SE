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
		return []byte(`{}`), nil
	}
	a, ok := g.answers[path]
	if !ok {
		g.t.Fatalf("gh api %s was not recorded", path)
	}
	return []byte(a), nil
}

func activity(n int) string {
	return fmt.Sprintf("repos/o/r/activity?ref=refs/heads/issue-%d&per_page=1", n)
}

func pushed(when string) string { return `[{"timestamp":"` + when + `"}]` }

func labelled(n int, label string) string {
	return fmt.Sprintf(`{"number":%d,"title":"t%d","state":"open","html_url":"u%d","labels":[{"name":"se"},{"name":%q}],"issue_dependencies_summary":{"total_blocked_by":0}}`, n, n, n, label)
}

func blockedBy(n, total int) string {
	return fmt.Sprintf(`{"number":%d,"title":"t%d","state":"open","html_url":"u%d","issue_dependencies_summary":{"total_blocked_by":%d}}`, n, n, n, total)
}

func TestAFreshClaimIsNotStuckAndAStaleOneIs(t *testing.T) {
	g := newGithub(t, map[string]string{
		listPath:    `[` + open(1, "") + `,` + open(2, "") + `,` + open(3, "") + `,` + open(4, "") + `]`,
		refsPath:    `[{"ref":"refs/heads/issue-1"},{"ref":"refs/heads/issue-2"},{"ref":"refs/heads/issue-3"},{"ref":"refs/heads/issue-4"}]`,
		activity(1): pushed(fresh),
		activity(2): pushed(stale),
		// A takeover renews the lease, however old the last push.
		activity(3): pushed(stale),
		// A branch GitHub keeps no push record of is stuck.
		activity(4): `[]`,
	})
	g.comments[3] = []comment{{ID: 1, Body: "<!-- se:takeover 1 -->\nTaken over", Created: now.Add(-time.Hour)}}
	all, err := Source{Repo: repo, GH: g.gh, Now: clock}.Survey()
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
	if all[1].Why != "claimed by issue-2, stuck: nothing pushed since 2026-10-13T08:00:00Z" || all[0].Why != "claimed by issue-1" {
		t.Fatalf("%q %q", all[0].Why, all[1].Why)
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
		listPath:    `[` + open(3, "") + `,` + open(5, "") + `]`,
		refsPath:    `[{"ref":"refs/heads/issue-5"}]`,
		activity(5): pushed(stale),
	})
	s := Source{Repo: repo, GH: g.gh, Now: clock}
	if next, ok, _, err := s.Next(); err != nil || !ok || next.Number != 5 {
		t.Fatalf("next = %+v %v %v", next, ok, err)
	}
	took, ok, _, err := s.Take(b, 0)
	if err != nil || !ok || took.Number != 5 {
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
	if len(g.writes) != 1 || !strings.Contains(strings.Join(g.writes[0], " "), "<!-- se:takeover 1 -->") {
		t.Fatalf("writes %q", g.writes)
	}
	// The takeover renewed the lease: the next box finds #5 claimed, not stuck.
	all, err := s.Survey()
	if err != nil || all[1].Stuck || all[1].Takeovers != 1 {
		t.Fatalf("%+v %v", all, err)
	}
}

func TestOfTwoTakeoversTheFirstCommentWins(t *testing.T) {
	_, _, b := boxes(t)
	g := newGithub(t, map[string]string{
		listPath:    `[` + open(5, "") + `,` + open(6, "") + `]`,
		refsPath:    `[{"ref":"refs/heads/issue-5"}]`,
		activity(5): pushed(stale),
	})
	s := Source{Repo: repo, GH: g.gh, Now: clock}
	all, _, err := s.Sweep()
	if err != nil {
		t.Fatal(err)
	}
	// Another box read the same survey and commented first.
	g.say(5, "<!-- se:takeover 1 -->")
	if ok, err := s.TakeOver(b, all[0]); err != nil || ok {
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

func TestASecondStaleClaimGoesToAPerson(t *testing.T) {
	g := newGithub(t, map[string]string{
		listPath:    `[` + open(5, "") + `,` + open(6, "") + `]`,
		refsPath:    `[{"ref":"refs/heads/issue-5"}]`,
		activity(5): pushed(stale),
	})
	g.say(5, "<!-- se:takeover 1 -->\nTaken over")
	next, ok, flagged, err := Source{Repo: repo, GH: g.gh, Now: clock}.Next()
	if err != nil || !ok || next.Number != 6 || len(flagged) != 1 || flagged[0].Number != 5 {
		t.Fatalf("next %+v %v, flagged %+v, %v", next, ok, flagged, err)
	}
	want := [][]string{
		{"api", "-X", "POST", "-f", "labels[]=se-person", "repos/o/r/issues/5/labels"},
		{"api", "-X", "POST", "-f", "assignees[]=o", "repos/o/r/issues/5/assignees"},
	}
	if len(g.writes) != 3 || !reflect.DeepEqual(g.writes[:2], want) {
		t.Fatalf("writes %q", g.writes)
	}
	if c := g.writes[2]; c[len(c)-1] != "repos/o/r/issues/5/comments" || !strings.HasPrefix(c[len(c)-2], "body=<!-- se:person -->\nStuck a second time") {
		t.Fatalf("comment %q", c)
	}
}

func TestIssuesWaitingOnAPersonAndTheirTreesAreNeverOffered(t *testing.T) {
	g := newGithub(t, map[string]string{
		// #2 waits on a person; #3 is blocked by it, #4 by #3; #5 is free.
		listPath: `[` + labelled(2, PersonLabel) + `,` + blockedBy(3, 1) + `,` + blockedBy(4, 1) + `,` + open(5, "") + `]`,
		refsPath: `[{"ref":"refs/heads/issue-2"}]`,
		"repos/o/r/issues/3/dependencies/blocked_by?per_page=100": `[{"number":2,"state":"open"}]`,
		"repos/o/r/issues/4/dependencies/blocked_by?per_page=100": `[{"number":3,"state":"open"}]`,
	})
	g.say(2, "<!-- se:person -->\nStuck a second time.")
	s := Source{Repo: repo, GH: g.gh, Now: clock}
	if next, ok, _, err := s.Next(); err != nil || !ok || next.Number != 5 {
		t.Fatalf("next %+v %v %v", next, ok, err)
	}
	for n, why := range map[int]string{2: "waits on a person", 3: "blocked by #2", 4: "blocked by #3"} {
		if _, _, _, err := s.Take(t.TempDir(), n); err == nil || !strings.Contains(err.Error(), why) {
			t.Errorf("take %d: %v", n, err)
		}
	}
	waiting, err := s.Waiting()
	if want := []Waiting{{2, "t2", "u2", "Stuck a second time.", 2}}; err != nil || !reflect.DeepEqual(waiting, want) {
		t.Fatalf("waiting %+v %v", waiting, err)
	}
	if len(g.writes) != 0 {
		t.Fatalf("writes %q", g.writes)
	}
}

func TestResumeResetsTheTakeoverCount(t *testing.T) {
	g := newGithub(t, map[string]string{
		"repos/o/r/issues/5": labelled(5, PersonLabel),
		"repos/o/r/issues/6": open(6, ""),
		listPath:             `[` + open(5, "") + `]`,
		refsPath:             `[{"ref":"refs/heads/issue-5"}]`,
		activity(5):          pushed(stale),
	})
	g.say(5, "<!-- se:takeover 1 -->")
	g.say(5, "<!-- se:person -->\nStuck a second time.")
	s := Source{Repo: repo, GH: g.gh, Now: clock}
	if _, err := s.Resume(6); err == nil || !strings.Contains(err.Error(), "not an open issue waiting on a person") {
		t.Fatalf("resumed #6: %v", err)
	}
	if i, err := s.Resume(5); err != nil || i.Number != 5 {
		t.Fatalf("%+v %v", i, err)
	}
	if len(g.writes) != 2 || g.writes[0][len(g.writes[0])-1] != "repos/o/r/issues/5/comments" ||
		!reflect.DeepEqual(g.writes[1], []string{"api", "-X", "DELETE", "repos/o/r/issues/5/labels/se-person"}) {
		t.Fatalf("writes %q", g.writes)
	}
	// Back in the queue, still stale: the next take takes it over, round one.
	all, err := s.Survey()
	if err != nil || !all[0].Stuck || all[0].Takeovers != 0 || !all[0].Takeable() {
		t.Fatalf("%+v %v", all, err)
	}
}
