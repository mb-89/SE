// Internal test package: it reads the fake GitHub back through api.
package issues

import (
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
)

// moot is box a on issue-6, whose work main got from commit fix before the
// claim, and the fake GitHub holding leaf #6.
func moot(t *testing.T, answers map[string]string) (s Source, gh *github.Fake, a, fix string) {
	t.Helper()
	_, a = claimed(t)
	run(t, a, "checkout", "-q", "main")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "the fix, from another issue")
	fix = run(t, a, "rev-parse", "HEAD")
	run(t, a, "push", "-q", "origin", "main")
	run(t, a, "checkout", "-q", "issue-6")
	gh = landGH(t, answers)
	return Source{Proc: machineOf(t), Repo: repo, GitHub: gh, Clock: clock.NewFake(landedAt()), Disk: disk.NewFake()}, gh, a, fix
}

func TestFixedByClosesTheIssueNamingTheCommitOnMain(t *testing.T) {
	t.Parallel()
	s, gh, a, fix := moot(t, map[string]string{issue6: `{"number":6,"state":"open","title":"the work"}`})
	m, err := s.FixedBy(a, "", 6, fix[:8], qs, full)
	if err != nil {
		t.Fatal(err)
	}
	if want := (Moot{Issue: 6, Commit: fix, Subject: "the fix, from another issue", URL: "https://github.com/o/r/commit/" + fix}); m != want {
		t.Fatalf("%+v", m)
	}
	if it := issueAt(t, gh, 6); it.State != "closed" || it.StateReason != "completed" {
		t.Fatalf("%+v", it)
	}
	cs := commentsAt(t, gh, 6)
	if len(cs) != 2 || !strings.Contains(cs[0].Body, landingMark) || !strings.HasPrefix(cs[1].Body, "<!-- se:fixed-by "+fix+" -->") || !strings.Contains(cs[1].Body, m.URL) {
		t.Fatalf("%+v", cs)
	}
	l, ok, err := ParseLanding(cs[0].Body)
	if err != nil || !ok || !reflect.DeepEqual(l.Answers, full) || !l.Facts.Claimed.Equal(time.Date(2026, 1, 2, 10, 0, 0, 0, time.UTC)) {
		t.Fatalf("%+v %v %v", l, ok, err)
	}
	want := []string{"POST repos/o/r/issues/6/comments", "POST repos/o/r/issues/6/comments", "PATCH repos/o/r/issues/6"}
	if w := gh.Writes(); !reflect.DeepEqual(w, want) {
		t.Fatalf("writes %q", w)
	}
}

func TestFixedByRefusesWorkNotOnMainBeforeWriting(t *testing.T) {
	t.Parallel()
	s, gh, a, _ := moot(t, map[string]string{issue6: `{"number":6,"state":"open","title":"the work"}`})
	// The branch's own commit is not on main.
	work := run(t, a, "rev-parse", "HEAD")
	for sha, why := range map[string]string{work: "is not on origin/main", "nosuch": "names no commit", "--all": "takes the SHA"} {
		if _, err := s.FixedBy(a, "", 6, sha, qs, full); err == nil || !strings.Contains(err.Error(), why) {
			t.Errorf("%s: %v", sha, err)
		}
	}
	if _, err := s.FixedBy(a, "", 6, "HEAD~1", qs, map[string]string{"done": "x"}); err == nil || !strings.Contains(err.Error(), "left") {
		t.Errorf("%v", err)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("wrote %q", w)
	}
}

func TestFixedByRefusesAClosedIssueAParentAndAPullRequest(t *testing.T) {
	t.Parallel()
	for leaf, why := range map[string]string{
		`{"number":6,"state":"closed"}`:                                              "#6 is closed already",
		`{"number":6,"state":"open","sub_issues_summary":{"total":2,"completed":1}}`: "a parent holds no work",
		`{"number":6,"state":"open","pull_request":{}}`:                              "is a pull request",
	} {
		s, gh, a, fix := moot(t, map[string]string{issue6: leaf})
		if _, err := s.FixedBy(a, "", 6, fix, qs, full); err == nil || !strings.Contains(err.Error(), why) {
			t.Errorf("%s: %v", leaf, err)
		}
		if w := gh.Writes(); len(w) != 0 {
			t.Fatalf("wrote %q", w)
		}
	}
}
