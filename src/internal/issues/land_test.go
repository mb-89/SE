// Internal test package: it drives the unexported autoMerge.
package issues

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/io/proc"

	"github.com/mb-89/SE/src/internal/battery"
)

const (
	pullsPath = "repos/o/r/pulls?head=o:issue-6&base=main&state=open&per_page=100"
	pr14      = `{"number":14,"node_id":"PR_14","html_url":"https://github.com/o/r/pull/14"}`
	clean14   = `{"number":14,"node_id":"PR_14","html_url":"https://github.com/o/r/pull/14","mergeable_state":"clean"}`
	issue6    = "repos/o/r/issues/6"
	leaf6     = `{"number":6,"title":"the work","sub_issues_summary":{"total":0,"completed":0}}`
	comments6 = "repos/o/r/issues/6/comments?per_page=100"
	created6  = "repos/o/r/activity?ref=refs/heads/issue-6&activity_type=branch_creation&per_page=100"
)

// qs and full are a short list of landing questions and an answer to each.
var (
	qs   = []Question{{Key: "done", Question: "What does it deliver?"}, {Key: "left", Question: "What is left?"}}
	full = map[string]string{"done": "the landing", "left": "nothing"}
)

// landGH is a fake GitHub holding leaf #6, claimed at 10:00, and answers.
func landGH(t *testing.T, answers map[string]string) *github.Fake {
	t.Helper()
	for path, a := range map[string]string{issue6: leaf6, comments6: `[]`, created6: `[{"timestamp":"2026-01-02T10:00:00Z"}]`} {
		if _, ok := answers[path]; !ok {
			answers[path] = a
		}
	}
	return recorded(t, answers)
}

// pullOf reads PR n back from the fake GitHub.
func pullOf(t *testing.T, gh github.GitHub, n int) map[string]any {
	t.Helper()
	out, err := gh.Get(fmt.Sprintf("repos/o/r/pulls/%d", n))
	if err != nil {
		t.Fatal(err)
	}
	var p map[string]any
	if err := json.Unmarshal(out, &p); err != nil {
		t.Fatal(err)
	}
	return p
}

// claimed is box a on issue-6, claimed from origin's main, with one commit of work.
func claimed(t *testing.T) (origin, a string) {
	t.Helper()
	origin, a, _ = boxes(t)
	if ok, err := (Source{Proc: machine}).Claim(a, 6); err != nil || !ok {
		t.Fatalf("claim: %v %v", ok, err)
	}
	run(t, a, "commit", "-q", "--allow-empty", "-m", "work")
	return origin, a
}

func passes(string) error { return nil }

// battered is a check that passes and records on d the tree it ran over, as
// tests/check.sh does.
func battered(d disk.Disk) func(string) error {
	return func(dir string) error {
		tree, err := battery.Tree(machine, dir)
		if err != nil {
			return err
		}
		_, err = battery.Pass(d, machine, dir, tree)
		return err
	}
}

// landedAt is when the tests land: 90 minutes after landGH's claim.
func landedAt() time.Time { return time.Date(2026, 1, 2, 11, 30, 0, 0, time.UTC) }

func TestLandPushesOpensThePRAndTurnsOnAutoMerge(t *testing.T) {
	t.Parallel()
	origin, a := claimed(t)
	gh := landGH(t, map[string]string{pullsPath: `[]`})
	// The se commands run in the checkout recorded 30 GitHub requests.
	d := disk.NewFake()
	if err := RecordRequests(d, a, "issue pull", 30, landedAt()); err != nil {
		t.Fatal(err)
	}
	l, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: clock.NewFake(landedAt()), Disk: d}.Land(a, "", qs, full, battered(d))
	if err != nil {
		t.Fatal(err)
	}
	// The PR is the repository's next number, after #6.
	if want := (Landing{Issue: 6, Number: 7, URL: "https://github.com/o/r/pull/7", Created: true}); l != want {
		t.Fatalf("%+v", l)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, a, "rev-parse", "HEAD"); got != want {
		t.Fatalf("origin's issue-6 is %s, want %s", got, want)
	}
	body, err := Landed{Issue: 6, Answers: full, Facts: Facts{
		Claimed: time.Date(2026, 1, 2, 10, 0, 0, 0, time.UTC), Landed: landedAt(), Minutes: 90, Commits: 1,
		// Those 30, and the 4 this land had made when it counted them (the manifest lookup and the battery status among them).
		Requests: 34,
	}}.Comment(qs)
	if err != nil {
		t.Fatal(err)
	}
	if got := commentsAt(t, gh, 6); len(got) != 1 || got[0].Body != body || !strings.Contains(body, "- GitHub requests: 34\n") {
		t.Fatalf("the landing comment is %+v, want\n%s", got, body)
	}
	want := []string{"POST repos/o/r/statuses/" + run(t, a, "rev-parse", "HEAD"), "POST repos/o/r/issues/6/comments", "POST repos/o/r/pulls", "POST graphql"}
	if w := gh.Writes(); !reflect.DeepEqual(w, want) {
		t.Fatalf("writes\n%q\nwant\n%q", w, want)
	}
	pr := pullOf(t, gh, 7)
	if pr["title"] != "the work" || pr["body"] != "Fixes #6" || pr["head"].(map[string]any)["ref"] != "issue-6" || pr["base"].(map[string]any)["ref"] != "main" ||
		pr["auto_merge"].(map[string]any)["merge_method"] != "squash" {
		t.Fatalf("the PR is %+v", pr)
	}
	if !strings.Contains(autoMerge, "mergeMethod: SQUASH") {
		t.Fatal(autoMerge)
	}
}

// profiles is a check that passes and leaves a battery profile, as tests/check.sh does.
func profiles(t *testing.T, d disk.Disk, p battery.Profile) func(string) error {
	t.Helper()
	return func(dir string) error {
		data, err := json.Marshal(p)
		if err != nil {
			return err
		}
		at := filepath.Join(dir, battery.Dir)
		if err := d.MkdirAll(at); err != nil {
			return err
		}
		if err := d.WriteFile(filepath.Join(at, battery.ProfileFile), data); err != nil {
			return err
		}
		return battered(d)(dir)
	}
}

var profile = battery.Profile{
	TotalMs:       1234,
	Steps:         []battery.Step{{Name: "go test", Ms: 1234}},
	Slowest:       []battery.Test{{Package: "p", Name: "TestSlow", Ms: 900}},
	SlowestPlugin: []battery.Test{{Package: "tests/se.test.ts", Name: "a slow hook", Ms: 150}},
	Overruns:      []string{"step go test took 1234ms, over its budget of 1000ms"},
	Unbudgeted:    []string{"step new has no budget in spec/budgets.yaml"},
}

func TestThePRBodyAndTheLandingFactsShowTheBatteryProfile(t *testing.T) {
	t.Parallel()
	_, a := claimed(t)
	d := disk.NewFake()
	gh := landGH(t, map[string]string{pullsPath: `[]`})
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: clock.NewFake(landedAt()), Disk: d}).Land(a, "", qs, full, profiles(t, d, profile)); err != nil {
		t.Fatal(err)
	}
	opened, _ := pullOf(t, gh, 7)["body"].(string)
	opened = "body=" + opened
	posted := "body=" + commentsAt(t, gh, 6)[0].Body
	if want := "body=Fixes #6\n\n" + profile.Markdown(); opened != want {
		t.Errorf("the PR body is\n%s\nwant\n%s", opened, want)
	}
	for _, want := range []string{"Total: **1234ms**", "| TestSlow | p | 900 |", "| a slow hook | tests/se.test.ts | 150 |", "**Over budget:** step go test took 1234ms"} {
		if !strings.Contains(opened, want) {
			t.Errorf("the PR body lacks %q", want)
		}
	}
	got, ok, err := ParseLanding(strings.TrimPrefix(posted, "body="))
	if err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	if got.Facts.BatteryMs != 1234 || !reflect.DeepEqual(got.Facts.Slowest, []string{"p TestSlow 900ms"}) ||
		!reflect.DeepEqual(got.Facts.SlowestPlugin, []string{"tests/se.test.ts a slow hook 150ms"}) ||
		!reflect.DeepEqual(got.Facts.Overruns, profile.Overruns) || !reflect.DeepEqual(got.Facts.Unbudgeted, profile.Unbudgeted) {
		t.Errorf("facts = %+v", got.Facts)
	}
	if !strings.Contains(posted, "- **no budget:** step new has no budget") {
		t.Errorf("the landing comment does not show the step without a budget:\n%s", posted)
	}
	if !strings.Contains(posted, "- **over budget:** step go test took 1234ms") {
		t.Errorf("the landing comment does not show the overrun:\n%s", posted)
	}
}

func TestLandAgainUpdatesTheOpenPRsProfile(t *testing.T) {
	t.Parallel()
	_, a := claimed(t)
	d := disk.NewFake()
	gh := landGH(t, map[string]string{pullsPath: `[` + pr14 + `]`})
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}).Land(a, "", qs, full, profiles(t, d, profile)); err != nil {
		t.Fatal(err)
	}
	if body := pullOf(t, gh, 14)["body"]; body != "Fixes #6\n\n"+profile.Markdown() {
		t.Fatalf("the open PR's body was not updated: %q", body)
	}
}

func TestLandAgainPushesAndReportsTheOpenPR(t *testing.T) {
	t.Parallel()
	origin, a := claimed(t)
	run(t, a, "push", "-q", "origin", "HEAD:issue-6")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "fix ci")
	gh := landGH(t, map[string]string{pullsPath: `[` + pr14 + `]`})
	d := disk.NewFake()
	l, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}.Land(a, "", qs, full, battered(d))
	if err != nil || l.Created || l.Number != 14 {
		t.Fatalf("%+v %v", l, err)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, a, "rev-parse", "HEAD"); got != want {
		t.Fatalf("origin's issue-6 is %s, want %s", got, want)
	}
	for _, w := range gh.Writes() {
		if w == "POST repos/o/r/pulls" {
			t.Fatalf("opened a second PR: %q", gh.Writes())
		}
	}
}

func TestLandMergesAPRWithNothingToWaitFor(t *testing.T) {
	t.Parallel()
	_, a := claimed(t)
	// No check is pending on #14: GitHub calls it clean.
	gh := landGH(t, map[string]string{pullsPath: `[` + clean14 + `]`})
	d := disk.NewFake()
	l, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}.Land(a, "", qs, full, battered(d))
	if err != nil || !l.Merged {
		t.Fatalf("%+v %v", l, err)
	}
	if pr := pullOf(t, gh, 14); pr["merged"] != true || pr["state"] != "closed" {
		t.Fatalf("%+v", pr)
	}
}

func TestLandTurnsOnAutoMergeWhereGraphQLIsRefused(t *testing.T) {
	t.Parallel()
	_, a := claimed(t)
	gh := landGH(t, map[string]string{pullsPath: `[` + pr14 + `]`})
	gh.Proxy = true
	d := disk.NewFake()
	l, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}.Land(a, "", qs, full, battered(d))
	if err != nil || l.Merged || l.Number != 14 {
		t.Fatalf("%+v %v", l, err)
	}
	if w := gh.Writes(); w[len(w)-1] != "PUT repos/o/r/pulls/14/ccr/auto_merge" || pullOf(t, gh, 14)["auto_merge"] == nil {
		t.Fatalf("%q", w)
	}
}

func TestLandSaysWhenAutoMergeFails(t *testing.T) {
	t.Parallel()
	_, a := claimed(t)
	gh := landGH(t, map[string]string{pullsPath: `[` + pr14 + `]`})
	gh.NoAutoMerge = true
	d := disk.NewFake()
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}).Land(a, "", qs, full, battered(d)); err == nil || !strings.Contains(err.Error(), "PR #14") || !strings.Contains(err.Error(), "auto-merge is not on") {
		t.Fatalf("%v", err)
	}
}

// checkout is a fake git's one checkout, /a: the branch it is on and what
// git status says of it, with an origin whose main it already holds and
// that has no copy of the branch. It does only what land asks before it pushes.
type checkout struct{ branch, dirty string }

func (w *checkout) git(c proc.Cmd) int {
	switch args := strings.Join(c.Args, " "); args {
	case "rev-parse --abbrev-ref HEAD":
		fmt.Fprintln(c.Stdout, w.branch)
	case "status --porcelain":
		_, _ = fmt.Fprint(c.Stdout, w.dirty)
	case "fetch -q origin main", "merge -q --no-edit origin/main":
	case "fetch -q origin refs/heads/" + w.branch + ":refs/remotes/origin/" + w.branch:
		fmt.Fprintf(c.Stderr, "fatal: couldn't find remote ref refs/heads/%s\n", w.branch)
		return 128
	default:
		fmt.Fprintf(c.Stderr, "fatal: this git only reads /a: %s\n", c.Args)
		return 128
	}
	return 0
}

func TestLandRefusesBeforePushing(t *testing.T) {
	t.Parallel()
	// It reads the issue, and writes nothing.
	gh := landGH(t, map[string]string{})
	w := &checkout{branch: "issue-6"}
	m := proc.NewFake()
	m.Install("git", w.git)
	land := func(check func(string) error) error {
		_, err := Source{Proc: m, Repo: repo, GitHub: gh, Clock: atNow(), Disk: disk.NewFake()}.Land("/a", "", qs, full, check)
		return err
	}
	fails := func(string) error { return errors.New("go test: FAIL") }
	if err := land(fails); err == nil || !strings.Contains(err.Error(), "nothing was pushed: go test: FAIL") {
		t.Fatalf("%v", err)
	}
	w.dirty = "?? x\n"
	checked := false
	if err := land(func(string) error { checked = true; return nil }); err == nil || !strings.Contains(err.Error(), "not committed") || checked {
		t.Fatalf("%v, checked %v", err, checked)
	}
	w.branch, w.dirty = "main", ""
	if err := land(passes); err == nil || !strings.Contains(err.Error(), "issue-<n> branch") {
		t.Fatalf("%v", err)
	}
	for _, line := range m.Lines() {
		if strings.HasPrefix(line, "git push") {
			t.Fatalf("a refused land pushed: %s", line)
		}
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused land wrote %q", w)
	}
}

func TestLandRefusesAParent(t *testing.T) {
	t.Parallel()
	origin, a := claimed(t)
	gh := landGH(t, map[string]string{issue6: `{"number":6,"title":"the tree","sub_issues_summary":{"total":2,"completed":1}}`})
	checked := false
	_, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: disk.NewFake()}.Land(a, "", qs, full, func(string) error { checked = true; return nil })
	if err == nil || !strings.Contains(err.Error(), "a parent holds no work") || checked {
		t.Fatalf("%v, checked %v", err, checked)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("%q", w)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, origin, "rev-parse", "main"); got != want {
		t.Fatalf("a refused land moved issue-6 to %s", got)
	}
}

// claimedBy is claimed with the second box b: a is on issue-6 with one commit
// of work, both able to merge.
func claimedBy(t *testing.T) (origin, a, b string) {
	t.Helper()
	origin, a, b = boxes(t)
	for _, d := range []string{a, b} {
		run(t, d, "config", "user.name", "t")
		run(t, d, "config", "user.email", "t@t")
	}
	if ok, err := (Source{Proc: machine}).Claim(a, 6); err != nil || !ok {
		t.Fatalf("claim: %v %v", ok, err)
	}
	commitFile(t, a, "work", "a")
	return origin, a, b
}

// commitFile commits name holding text in dir.
func commitFile(t *testing.T, dir, name, text string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	run(t, dir, "add", name)
	run(t, dir, "commit", "-q", "-m", name)
}

func TestLandMergesTheBranchAndMainInBeforeTheCheck(t *testing.T) {
	t.Parallel()
	origin, a, b := claimedBy(t)
	run(t, a, "push", "-q", "origin", "HEAD:issue-6")
	commitFile(t, a, "fix", "a")
	// On origin, main moved, and another box (a takeover's) pushed to issue-6.
	run(t, b, "fetch", "-q", "origin")
	run(t, b, "checkout", "-q", "-b", "issue-6", "origin/issue-6")
	commitFile(t, b, "pushed", "b")
	run(t, b, "push", "-q", "origin", "issue-6")
	run(t, b, "checkout", "-q", "main")
	commitFile(t, b, "rule", "b")
	run(t, b, "push", "-q", "origin", "main")
	gh := landGH(t, map[string]string{pullsPath: `[` + pr14 + `]`})
	var saw []string
	d := disk.NewFake()
	check := func(dir string) error {
		for _, f := range []string{"work", "fix", "pushed", "rule"} {
			if _, err := os.Stat(filepath.Join(dir, f)); err == nil {
				saw = append(saw, f)
			}
		}
		return battered(d)(dir)
	}
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}).Land(a, "", qs, full, check); err != nil {
		t.Fatal(err)
	}
	if want := []string{"work", "fix", "pushed", "rule"}; !reflect.DeepEqual(saw, want) {
		t.Fatalf("the check saw %v, want %v", saw, want)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, a, "rev-parse", "HEAD"); got != want {
		t.Fatalf("origin's issue-6 is %s, want %s", got, want)
	}
}

func TestLandStopsWhereMainConflicts(t *testing.T) {
	t.Parallel()
	origin, a, b := claimedBy(t)
	before := run(t, origin, "rev-parse", "issue-6")
	commitFile(t, b, "work", "b")
	run(t, b, "push", "-q", "origin", "main")
	head := run(t, a, "rev-parse", "HEAD")
	gh := landGH(t, map[string]string{})
	checked := false
	_, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: disk.NewFake()}.Land(a, "", qs, full, func(string) error { checked = true; return nil })
	if err == nil || !strings.Contains(err.Error(), "merging origin/main into issue-6 conflicts") || checked {
		t.Fatalf("%v, checked %v", err, checked)
	}
	if got := run(t, a, "rev-parse", "HEAD"); got != head {
		t.Fatalf("a moved to %s", got)
	}
	if dirty := run(t, a, "status", "--porcelain"); dirty != "" {
		t.Fatalf("the merge was left half done:\n%s", dirty)
	}
	if got := run(t, origin, "rev-parse", "issue-6"); got != before {
		t.Fatalf("a refused land moved issue-6 to %s", got)
	}
}
