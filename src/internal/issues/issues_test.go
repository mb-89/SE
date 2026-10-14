// Internal test package: its fakes serve the package's other internal tests.
package issues

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

const repo = "o/r"

// recorded answers gh api calls from a table keyed by path; a call it does not
// hold fails the test, so a test names every request the rules make.
func recorded(t *testing.T, answers map[string]string) GH {
	t.Helper()
	return func(args ...string) ([]byte, error) {
		path := args[len(args)-1]
		if args[0] != "api" {
			t.Fatalf("gh %v: only gh api is expected", args)
		}
		a, ok := answers[path]
		if !ok {
			t.Fatalf("gh api %s was not recorded", path)
		}
		return []byte(a), nil
	}
}

const (
	listPath = "repos/o/r/issues?labels=se&state=open&per_page=100"
	refsPath = "repos/o/r/git/matching-refs/heads/issue-"
)

// unblocked records an empty "blocked by" answer for each issue n, as every
// unclaimed issue's links are asked for.
func unblocked(answers map[string]string, ns ...int) map[string]string {
	for _, n := range ns {
		answers[links(n)] = `[]`
	}
	return answers
}

func links(n int) string {
	return fmt.Sprintf("repos/o/r/issues/%d/dependencies/blocked_by?per_page=100", n)
}

// now is the tests' clock; a branch pushed at fresh is inside the lease, one
// pushed at stale is not.
var (
	now   = time.Date(2026, 10, 13, 12, 0, 0, 0, time.UTC)
	clock = func() time.Time { return now }
	fresh = now.Add(-time.Hour).Format(time.RFC3339)
	stale = now.Add(-4 * time.Hour).Format(time.RFC3339)
)

func activity(n int) string {
	return fmt.Sprintf("repos/o/r/activity?ref=refs/heads/issue-%d&per_page=1", n)
}

func pushed(when string) string { return `[{"timestamp":"` + when + `"}]` }

// pushedAt records that each claimed branch issue-<n> was last pushed at when,
// and, where no test said otherwise, that nothing blocks its issue: a claim's
// links are read too, as one that waits on its blockers is not stuck.
func pushedAt(answers map[string]string, when string, ns ...int) map[string]string {
	for _, n := range ns {
		answers[activity(n)] = pushed(when)
		if _, ok := answers[links(n)]; !ok {
			answers[links(n)] = `[]`
		}
	}
	return answers
}

func open(n int, body string) string {
	return fmt.Sprintf(`{"number":%d,"title":"t%d","body":%q,"state":"open","html_url":"u%d","issue_dependencies_summary":{"total_blocked_by":0}}`, n, n, body, n)
}

func survey(t *testing.T, answers map[string]string) map[int]string {
	t.Helper()
	all, err := Source{Repo: repo, GH: recorded(t, answers), Now: clock}.Survey()
	if err != nil {
		t.Fatal(err)
	}
	got := map[int]string{}
	prev := 0
	for _, st := range all {
		if st.Number <= prev {
			t.Fatalf("not lowest first: %+v", all)
		}
		prev = st.Number
		got[st.Number] = st.Why
	}
	return got
}

func TestTheRecordedRepositoryNamesTheNextIssue(t *testing.T) {
	read := func(name string) string {
		data, err := os.ReadFile(filepath.Join("testdata", name))
		if err != nil {
			t.Fatal(err)
		}
		return string(data)
	}
	// Recorded from mb-89/SE: #5 claimed; #6 says "Blocked by: #5" in its
	// body, which is no blocker, as only native links are.
	gh := recorded(t, map[string]string{
		"repos/mb-89/SE/issues?labels=se&state=open&per_page=100":      read("issues.json"),
		"repos/mb-89/SE/git/matching-refs/heads/issue-":                read("refs.json"),
		"repos/mb-89/SE/issues/6/dependencies/blocked_by?per_page=100": `[]`,
		"repos/mb-89/SE/issues/7/dependencies/blocked_by?per_page=100": `[]`,
		"repos/mb-89/SE/activity?ref=refs/heads/issue-5&per_page=1":    pushed(fresh),
		"repos/mb-89/SE/issues/5/dependencies/blocked_by?per_page=100": `[]`,
	})
	s := Source{Repo: "mb-89/SE", GH: gh, Now: clock}
	all, err := s.Survey()
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"claimed by issue-5", "", ""}
	for k, st := range all {
		if st.Number != 5+k || st.Why != want[k] {
			t.Errorf("%d: #%d %q, want #%d %q", k, st.Number, st.Why, 5+k, want[k])
		}
	}
	next, ok, err := s.Next()
	if err != nil || !ok || next.Number != 6 || !strings.Contains(next.URL, "/issues/6") {
		t.Fatalf("next = %+v %v %v", next, ok, err)
	}
}

func TestOnlyOpenSeIssuesAreTheFleets(t *testing.T) {
	// The list is already filtered by label and state; a pull request in it is dropped.
	got := survey(t, unblocked(map[string]string{
		listPath: `[` + open(4, "") + `,{"number":3,"state":"open","pull_request":{}}]`,
		refsPath: `[]`,
	}, 4))
	if !reflect.DeepEqual(got, map[int]string{4: ""}) {
		t.Fatalf("%v", got)
	}
}

func TestLowestReadyNumberComesFirst(t *testing.T) {
	gh := recorded(t, unblocked(map[string]string{
		listPath: `[` + open(9, "") + `,` + open(3, "") + `]` + `[` + open(5, "") + `]`, // two pages
		refsPath: `[]`,
	}, 3, 5, 9))
	next, ok, err := Source{Repo: repo, GH: gh}.Next()
	if err != nil || !ok || next.Number != 3 || next.Title != "t3" {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
}

func TestAClaimedBranchHoldsItsIssue(t *testing.T) {
	got := survey(t, pushedAt(unblocked(map[string]string{
		listPath: `[` + open(1, "") + `,` + open(2, "") + `,` + open(12, "") + `]`,
		// issue-12 is not issue-1; issue-2-old is not issue-2.
		refsPath: `[{"ref":"refs/heads/issue-1"},{"ref":"refs/heads/issue-2-old"}]`,
	}, 2, 12), fresh, 1))
	if !reflect.DeepEqual(got, map[int]string{1: "claimed by issue-1", 2: "", 12: ""}) {
		t.Fatalf("%v", got)
	}
}

func TestNativeLinksBlockWhileTheirIssuesAreOpen(t *testing.T) {
	native := func(n, total int) string {
		return fmt.Sprintf(`{"number":%d,"title":"t","state":"open","issue_dependencies_summary":{"total_blocked_by":%d}}`, n, total)
	}
	got := survey(t, map[string]string{
		listPath: `[` + native(4, 2) + `,` + native(5, 1) + `,` + native(6, 0) +
			`,{"number":7,"state":"open"}` +
			// A body line is no blocker; only the native link counts.
			`,{"number":8,"state":"open","body":"Blocked by: #20, #22","issue_dependencies_summary":{"total_blocked_by":1}}` +
			`,{"number":9,"state":"open","body":"Blocked by: #20","issue_dependencies_summary":{"total_blocked_by":0}}]`,
		refsPath: `[]`,
		"repos/o/r/issues/4/dependencies/blocked_by?per_page=100": `[{"number":20,"state":"open"},{"number":21,"state":"closed"}]`,
		"repos/o/r/issues/5/dependencies/blocked_by?per_page=100": `[{"number":21,"state":"closed"}]`,
		"repos/o/r/issues/6/dependencies/blocked_by?per_page=100": `[]`,
		"repos/o/r/issues/7/dependencies/blocked_by?per_page=100": `[]`,
		"repos/o/r/issues/8/dependencies/blocked_by?per_page=100": `[{"number":20,"state":"open"}]`,
		"repos/o/r/issues/9/dependencies/blocked_by?per_page=100": `[]`,
	})
	want := map[int]string{4: "blocked by #20", 5: "", 6: "", 7: "", 8: "blocked by #20", 9: ""}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("%v, want %v", got, want)
	}
}

func TestAStaleSummaryDoesNotMakeABlockedIssueReady(t *testing.T) {
	// Right after #6 is linked as blocked by #8, the list's summary can
	// still count 0; the links already name #8.
	gh := recorded(t, map[string]string{
		listPath:    `[` + open(6, "") + `,` + open(8, "") + `]`,
		refsPath:    `[{"ref":"refs/heads/issue-8"}]`,
		links(6):    `[{"number":8,"state":"open"}]`,
		links(8):    `[]`,
		activity(8): pushed(fresh),
	})
	s := Source{Repo: repo, GH: gh, Now: clock}
	if next, ok, err := s.Next(); err != nil || ok {
		t.Fatalf("next = %+v %v %v", next, ok, err)
	}
	if _, _, err := s.Take(t.TempDir(), 6); err == nil || !strings.Contains(err.Error(), "blocked by #8") {
		t.Fatalf("%v", err)
	}
}

func TestNothingReady(t *testing.T) {
	for name, list := range map[string]string{
		"no issues": `[]`,
		"all held":  `[` + open(1, "") + `,{"number":2,"state":"open","issue_dependencies_summary":{"total_blocked_by":1}}]`,
	} {
		gh := recorded(t, map[string]string{
			listPath: list,
			refsPath: `[{"ref":"refs/heads/issue-1"}]`,
			"repos/o/r/issues/2/dependencies/blocked_by?per_page=100": `[{"number":1,"state":"open"}]`,
			links(1):    `[]`,
			activity(1): pushed(fresh),
		})
		if next, ok, err := (Source{Repo: repo, GH: gh, Now: clock}).Next(); err != nil || ok {
			t.Errorf("%s: %+v %v %v", name, next, ok, err)
		}
	}
}

func TestRepoReadsOrigin(t *testing.T) {
	for url, want := range map[string]string{
		"https://github.com/mb-89/SE":              "mb-89/SE",
		"https://github.com/mb-89/SE.git":          "mb-89/SE",
		"git@github.com:mb-89/SE.git":              "mb-89/SE",
		"http://proxy@127.0.0.1:1234/git/mb-89/SE": "mb-89/SE",
	} {
		dir := t.TempDir()
		run(t, dir, "init", "-q")
		run(t, dir, "remote", "add", "origin", url)
		if got, err := Repo(dir); err != nil || got != want {
			t.Errorf("%s: %q %v", url, got, err)
		}
	}
}

func run(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v %s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

// boxes makes a bare origin with a main and two clones of it, two boxes.
func boxes(t *testing.T) (origin, a, b string) {
	t.Helper()
	root := t.TempDir()
	origin, a, b = filepath.Join(root, "origin.git"), filepath.Join(root, "a"), filepath.Join(root, "b")
	run(t, root, "init", "-q", "--bare", "-b", "main", origin)
	run(t, root, "clone", "-q", origin, a)
	run(t, a, "checkout", "-q", "-b", "main")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "start")
	run(t, a, "push", "-q", "origin", "main")
	run(t, root, "clone", "-q", origin, b)
	return origin, a, b
}

func TestTheSecondClaimIsRefused(t *testing.T) {
	origin, a, b := boxes(t)
	if ok, err := Claim(a, 5); err != nil || !ok {
		t.Fatalf("first claim: %v %v", ok, err)
	}
	if got := run(t, a, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-5" {
		t.Fatalf("a is on %s", got)
	}
	if got := run(t, a, "rev-parse", "--abbrev-ref", "@{upstream}"); got != "origin/issue-5" {
		t.Fatalf("a tracks %s", got)
	}
	// main moves on, so a plain push of the newer main would fast-forward
	// issue-5; the claim must still be refused.
	run(t, a, "commit", "-q", "--allow-empty", "-m", "more")
	run(t, a, "push", "-q", "origin", "HEAD:main")
	if ok, err := Claim(b, 5); err != nil || ok {
		t.Fatalf("second claim: %v %v", ok, err)
	}
	if got := run(t, b, "rev-parse", "--abbrev-ref", "HEAD"); got != "main" {
		t.Fatalf("b moved to %s", got)
	}
	if got, want := run(t, origin, "rev-parse", "issue-5"), run(t, origin, "rev-parse", "main~1"); got != want {
		t.Fatalf("issue-5 moved to %s, want %s", got, want)
	}
}

func TestATakeRefusedMovesToTheNextIssue(t *testing.T) {
	_, a, b := boxes(t)
	// Both boxes read the same issues; a claims #5 before b pushes.
	gh := recorded(t, unblocked(map[string]string{
		listPath: `[` + open(5, "") + `,` + open(6, "") + `]`,
		refsPath: `[]`,
	}, 5, 6))
	s := Source{Repo: repo, GH: gh}
	if took, ok, err := s.Take(a, 0); err != nil || !ok || took.Number != 5 {
		t.Fatalf("a took %+v %v %v", took, ok, err)
	}
	if took, ok, err := s.Take(b, 5); err != nil || !ok || took.Number != 6 {
		t.Fatalf("b took %+v %v %v", took, ok, err)
	}
	if got := run(t, b, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-6" {
		t.Fatalf("b is on %s", got)
	}
	if took, ok, err := s.Take(b, 0); err != nil || ok {
		t.Fatalf("nothing left, yet b took %+v %v %v", took, ok, err)
	}
}

func TestTakeRefusesAnIssueThatIsNotReady(t *testing.T) {
	gh := recorded(t, map[string]string{
		listPath: `[` + open(1, "") + `,{"number":2,"state":"open","issue_dependencies_summary":{"total_blocked_by":1}}]`,
		refsPath: `[]`,
		links(1): `[]`,
		links(2): `[{"number":1,"state":"open"}]`,
	})
	s := Source{Repo: repo, GH: gh}
	if _, _, err := s.Take(t.TempDir(), 2); err == nil || !strings.Contains(err.Error(), "blocked by #1") {
		t.Fatalf("%v", err)
	}
	if _, _, err := s.Take(t.TempDir(), 3); err == nil || !strings.Contains(err.Error(), "not an open issue") {
		t.Fatalf("%v", err)
	}
}
