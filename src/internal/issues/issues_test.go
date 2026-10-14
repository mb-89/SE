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

	"github.com/mb-89/SE/src/modules/io/clock"
	"github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/github"
	"github.com/mb-89/SE/src/modules/io/proc"
)

const repo = "o/r"

// recorded is a fake GitHub seeded from recorded gh answers, keyed by path.
func recorded(t *testing.T, answers map[string]string) *github.Fake {
	t.Helper()
	return recordedAt(t, atNow(), answers)
}

// recordedAt is recorded on the clock c, which the code under test shares.
func recordedAt(t *testing.T, c *clock.Fake, answers map[string]string) *github.Fake {
	t.Helper()
	f := github.NewFake(c)
	seed(t, f, answers)
	return f
}

// seed adds recorded answers to what the fake GitHub holds.
func seed(t *testing.T, f *github.Fake, answers map[string]string) {
	t.Helper()
	if err := f.Seed(answers); err != nil {
		t.Fatal(err)
	}
}

// issueAt reads issue n back from the fake GitHub.
func issueAt(t *testing.T, gh github.GitHub, n int) issue {
	t.Helper()
	got, err := api[issue](Source{Repo: repo, GitHub: gh}, fmt.Sprintf("repos/o/r/issues/%d", n), false)
	if err != nil {
		t.Fatal(err)
	}
	return got[0]
}

// labelled says whether the fake GitHub's issue n carries label l.
func labelled(t *testing.T, gh github.GitHub, n int, l string) bool {
	t.Helper()
	return issueAt(t, gh, n).labelled(l)
}

// commentsAt reads issue n's comments back from the fake GitHub, oldest first.
func commentsAt(t *testing.T, gh github.GitHub, n int) []comment {
	t.Helper()
	got, err := api[comment](Source{Repo: repo, GitHub: gh}, fmt.Sprintf("repos/o/r/issues/%d/comments", n), true)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

// never is a GitHub a test expects no call of.
type never struct{ t *testing.T }

func (n never) fail(what string) ([]byte, error) {
	n.t.Helper()
	n.t.Fatalf("GitHub was asked %s", what)
	return nil, nil
}

func (n never) Get(path string) ([]byte, error)  { return n.fail("for " + path) }
func (n never) List(path string) ([]byte, error) { return n.fail("for " + path) }
func (n never) Send(method, path string, _ ...github.Field) ([]byte, error) {
	return n.fail("to " + method + " " + path)
}
func (n never) GraphQL(string, ...github.Field) ([]byte, error) { return n.fail("a GraphQL query") }

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

// now is when the tests run; a branch pushed at fresh is inside the lease, one
// pushed at stale is not.
var (
	now   = time.Date(2026, 10, 13, 12, 0, 0, 0, time.UTC)
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

// manifested makes each issue n a manifest with one open leaf inside it,
// 1000+n, so a take at the top may have n: boxes take only manifests.
func manifested(answers map[string]string, ns ...int) map[string]string {
	for _, n := range ns {
		withLeaf(answers, n, 1000+n)
	}
	return answers
}

// withLeaf makes issue m a manifest with the open leaf inside it.
func withLeaf(answers map[string]string, m, leaf int) map[string]string {
	answers[fmt.Sprintf("repos/o/r/issues/%d/sub_issues?per_page=100", m)] = fmt.Sprintf(`[{"number":%d,"title":"t%d","state":"open","labels":[{"name":"se"}]}]`, leaf, leaf)
	return answers
}

// openRetro is open, labelled se-retro: a leaf a take at the top may have.
func openRetro(n int, body string) string {
	return fmt.Sprintf(`{"number":%d,"title":"t%d","body":%q,"state":"open","html_url":"u%d","labels":[{"name":"se-retro"}]}`, n, n, body, n)
}

func open(n int, body string) string {
	return fmt.Sprintf(`{"number":%d,"title":"t%d","body":%q,"state":"open","html_url":"u%d","issue_dependencies_summary":{"total_blocked_by":0}}`, n, n, body, n)
}

func survey(t *testing.T, answers map[string]string) map[int]string {
	t.Helper()
	all, err := Source{Git: machine, Repo: repo, GitHub: recorded(t, answers), Clock: atNow()}.Survey()
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
	t.Parallel()
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
		"repos/mb-89/SE/pulls?state=open&per_page=100":                 `[]`,
		"repos/mb-89/SE/issues/5/dependencies/blocked_by?per_page=100": `[]`,
		"repos/mb-89/SE/issues/6/dependencies/blocked_by?per_page=100": `[]`,
		"repos/mb-89/SE/issues/7/dependencies/blocked_by?per_page=100": `[]`,
		"repos/mb-89/SE/activity?ref=refs/heads/issue-5&per_page=1":    pushed(fresh),
	})
	s := Source{Git: machine, Repo: "mb-89/SE", GitHub: gh, Clock: atNow()}
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
	// #6 and #7 stand in no manifest, and boxes take only manifests: a take
	// at the top skips a bare leaf.
	for _, st := range all[1:] {
		if st.Bare != BareWhy || st.Ready() {
			t.Errorf("#%d: %+v", st.Number, st)
		}
	}
	if next, ok, err := s.Next(); err != nil || ok {
		t.Fatalf("next = %+v %v %v", next, ok, err)
	}
}

func TestOnlyOpenSeIssuesAreTheFleets(t *testing.T) {
	t.Parallel()
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
	t.Parallel()
	gh := recorded(t, manifested(unblocked(map[string]string{
		listPath: `[` + open(9, "") + `,` + open(3, "") + `]` + `[` + open(5, "") + `]`, // two pages
		refsPath: `[]`,
	}, 3, 5, 9), 3, 5, 9))
	next, ok, err := Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Next()
	if err != nil || !ok || next.Number != 3 || next.Title != "t3" {
		t.Fatalf("%+v %v %v", next, ok, err)
	}
}

func TestAClaimedBranchHoldsItsIssue(t *testing.T) {
	t.Parallel()
	got := survey(t, pushedAt(unblocked(map[string]string{
		listPath: `[` + open(1, "") + `,` + open(2, "") + `,` + open(12, "") + `]`,
		// issue-12 is not issue-1; issue-2-old is not issue-2.
		refsPath:      `[{"ref":"refs/heads/issue-1"},{"ref":"refs/heads/issue-2-old"}]`,
		openPullsPath: `[]`,
	}, 1, 2, 12), fresh, 1))
	if !reflect.DeepEqual(got, map[int]string{1: "claimed by issue-1", 2: "", 12: ""}) {
		t.Fatalf("%v", got)
	}
}

func TestNativeLinksBlockWhileTheirIssuesAreOpen(t *testing.T) {
	t.Parallel()
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
	t.Parallel()
	// Right after #6 is linked as blocked by #8, the list's summary can
	// still count 0; the links already name #8.
	gh := recorded(t, map[string]string{
		listPath:      `[` + open(6, "") + `,` + open(8, "") + `]`,
		refsPath:      `[{"ref":"refs/heads/issue-8"}]`,
		openPullsPath: `[]`,
		links(6):      `[{"number":8,"state":"open"}]`,
		links(8):      `[]`,
		activity(8):   pushed(fresh),
	})
	s := Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	if next, ok, err := s.Next(); err != nil || ok {
		t.Fatalf("next = %+v %v %v", next, ok, err)
	}
	if _, _, err := s.Take(t.TempDir(), 6); err == nil || !strings.Contains(err.Error(), "blocked by #8") {
		t.Fatalf("%v", err)
	}
}

func TestNothingReady(t *testing.T) {
	t.Parallel()
	for name, list := range map[string]string{
		"no issues": `[]`,
		"all held":  `[` + open(1, "") + `,{"number":2,"state":"open","issue_dependencies_summary":{"total_blocked_by":1}}]`,
	} {
		gh := recorded(t, map[string]string{
			listPath:      list,
			refsPath:      `[{"ref":"refs/heads/issue-1"}]`,
			openPullsPath: `[]`,
			links(1):      `[]`,
			"repos/o/r/issues/2/dependencies/blocked_by?per_page=100": `[{"number":1,"state":"open"}]`,
			links(1):    `[]`,
			activity(1): pushed(fresh),
		})
		if next, ok, err := (Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}).Next(); err != nil || ok {
			t.Errorf("%s: %+v %v %v", name, next, ok, err)
		}
	}
}

func TestRepoReadsOrigin(t *testing.T) {
	t.Parallel()
	for url, want := range map[string]string{
		"https://github.com/mb-89/SE":              "mb-89/SE",
		"https://github.com/mb-89/SE.git":          "mb-89/SE",
		"git@github.com:mb-89/SE.git":              "mb-89/SE",
		"http://proxy@127.0.0.1:1234/git/mb-89/SE": "mb-89/SE",
	} {
		m := git.NewFake(withOrigin("/w", url))
		if got, err := Repo(m, "/w"); err != nil || got != want {
			t.Errorf("%s: %q %v", url, got, err)
		}
	}
	m := git.NewFake(withOrigin("/w", ""))
	if _, err := Repo(m, "/w"); err == nil || !strings.Contains(err.Error(), "remote get-url origin") {
		t.Fatalf("a checkout without origin answered %v", err)
	}
}

// withOrigin is a git whose one checkout, dir, has origin at url; an empty url
// is no origin at all.
func withOrigin(dir, url string) proc.Program {
	return func(c proc.Cmd) int {
		switch {
		case c.Dir != dir:
			fmt.Fprintf(c.Stderr, "fatal: not a git repository: %s\n", c.Dir)
			return 128
		case strings.Join(c.Args, " ") != "remote get-url origin":
			fmt.Fprintf(c.Stderr, "git: %s is not what this git does\n", c.Args)
			return 1
		case url == "":
			fmt.Fprintln(c.Stderr, "error: No such remote 'origin'")
			return 2
		}
		fmt.Fprintln(c.Stdout, url)
		return 0
	}
}

// machine is the real git the tests that build git repositories still run;
// #137 moves them onto the fake.
var machine = git.Real(proc.Real(), env.Real())

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
	t.Parallel()
	origin, a, b := boxes(t)
	if ok, err := (Source{Git: machine}).Claim(a, 5); err != nil || !ok {
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
	if ok, err := (Source{Git: machine}).Claim(b, 5); err != nil || ok {
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
	t.Parallel()
	_, a, b := boxes(t)
	// Both boxes read the same issues, two retros (the leaves a box takes at
	// the top); a claims #5 before b pushes.
	retro := func(n int) string {
		return fmt.Sprintf(`{"number":%d,"title":"t%d","state":"open","html_url":"u%d","labels":[{"name":"se-retro"}]}`, n, n, n)
	}
	gh := recorded(t, unblocked(map[string]string{
		listPath: `[` + retro(5) + `,` + retro(6) + `]`,
		refsPath: `[]`,
	}, 5, 6))
	s := Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}
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
	t.Parallel()
	gh := recorded(t, map[string]string{
		listPath: `[` + open(1, "") + `,{"number":2,"state":"open","issue_dependencies_summary":{"total_blocked_by":1}}]`,
		refsPath: `[]`,
		links(1): `[]`,
		links(2): `[{"number":1,"state":"open"}]`,
	})
	s := Source{Git: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	if _, _, err := s.Take(t.TempDir(), 2); err == nil || !strings.Contains(err.Error(), "blocked by #1") {
		t.Fatalf("%v", err)
	}
	if _, _, err := s.Take(t.TempDir(), 3); err == nil || !strings.Contains(err.Error(), "not an open issue") {
		t.Fatalf("%v", err)
	}
}

func TestPagesAsksPageByPageUntilOneIsShort(t *testing.T) {
	t.Parallel()
	// One more comment than a page holds.
	all := make([]string, PerPage+1)
	for k := range all {
		all[k] = fmt.Sprintf(`{"id":%d,"body":"c%d","created_at":"2026-10-01T00:00:%02dZ"}`, k+1, k, k%60)
	}
	gh := recorded(t, map[string]string{"repos/o/r/issues/1/comments": "[" + strings.Join(all, ",") + "]"})
	path := "repos/o/r/issues/comments?since=2026-01-01T00:00:00Z&per_page=100"
	got, err := pages[comment](Source{Repo: repo, GitHub: gh}, path)
	if err != nil || len(got) != PerPage+1 {
		t.Fatalf("%d items, %v", len(got), err)
	}
}

// atNow is a fresh fake clock standing at now.
func atNow() *clock.Fake { return clock.NewFake(now) }
