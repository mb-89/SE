// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/issues"
)

// queuedAt reads the issues the box in ws queued, as se issue new recorded them.
func queuedAt(t *testing.T, d disk.Disk, ws string) []newIssue {
	t.Helper()
	data, err := d.ReadFile(filepath.Join(ws, ".se", ".runtime", "followups.json"))
	if err != nil {
		return nil
	}
	var q []newIssue
	if err := json.Unmarshal(data, &q); err != nil {
		t.Fatal(err)
	}
	return q
}

func TestABoxsIssueNewQueuesOneIssueAndWritesNothing(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	asBox(t)
	d, ws := onFake(t), filepath.FromSlash("/ws")
	newIn := func(args ...string) (int, string, string) {
		return se(t, append([]string{"issue", "new", "--workspace", ws, "--repo", "o/r"}, args...)...)
	}
	code, out, errs := newIn("--title", "ten", "--body", "what is left", "--blocked-by", "3,1", "--parent", "1", "--blocks", "3", "--final")
	if code != 0 || !strings.HasPrefix(out, `Queued "ten", not created`) || !strings.Contains(out, "se issue land, se issue supersede or se issue close --fixed-by") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	want := []newIssue{{Title: "ten", Body: "what is left", BlockedBy: []int{1, 3}, Parent: 1, Blocks: []int{3}, Final: true}}
	if q := queuedAt(t, d, ws); !reflect.DeepEqual(q, want) {
		t.Fatalf("queued %+v", q)
	}
	// A second is refused: a box files at most one issue.
	code, _, errs = newIn("--title", "eleven", "--body", "more", "--blocked-by", "none")
	if code != 1 || !strings.Contains(errs, `a box files at most one issue (issues/config/max-followups), and "ten" is queued already: fold both into one and pass --replace`) || !strings.Contains(errs, "--person") {
		t.Fatalf("exit %d, %q", code, errs)
	}
	// --replace puts the one folded issue in its place.
	code, out, errs = newIn("--json", "--title", "both", "--body", "all that is left", "--blocked-by", "none", "--person", "--replace")
	if code != 0 || !strings.Contains(out, `"queued":true,"title":"both","replaced":"ten"`) {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	if q := queuedAt(t, d, ws); len(q) != 1 || q[0].Title != "both" || !q[0].Person || q[0].BlockedBy != nil {
		t.Fatalf("queued %+v", q)
	}
	// What se issue new refuses before GitHub, a box's refuses too.
	if code, _, errs := newIn("--title", "x", "--body", "b", "--blocked-by", "none", "--person", "--review", "--replace"); code != 1 || !strings.Contains(errs, "--person takes neither") {
		t.Fatalf("exit %d, %q", code, errs)
	}
	if w := gh.Writes(); len(w) != 0 || fires(t) != 0 {
		t.Fatalf("a box's se issue new wrote %q, fired %d", w, fires(t))
	}
	// A session that is no box creates at once, and has nothing to replace.
	setenv(t, "CLAUDE_CODE_SESSION_ATTENDED", "1")
	if code, _, errs := newIn("--title", "x", "--body", "b", "--blocked-by", "none", "--replace"); code != 1 || !strings.Contains(errs, "this session is no box") {
		t.Fatalf("exit %d, %q", code, errs)
	}
	if code, out, errs := newIn("--title", "x", "--body", "b", "--blocked-by", "none"); code != 0 || !strings.HasPrefix(out, "Created #11 x\n") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
}

func TestASupersedeFilesTheQueuedIssueAsItsFollowup(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	asBox(t)
	d, ws := onFake(t), filepath.FromSlash("/ws")
	put(t, d, filepath.Join(ws, "left.md"), "the rest\n")
	if code, out, errs := se(t, "issue", "new", "--workspace", ws, "--repo", "o/r", "--title", "the rest", "--body-file", "left.md", "--blocked-by", "1", "--blocks", "3"); code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, out, errs := se(t, "issue", "supersede", "3", "--body", "which way?", "--workspace", ws, "--repo", "o/r")
	// #10 is the misc manifest the successor, #11, opened; #12 the follow-up.
	if code != 0 || !strings.HasPrefix(out, "Superseded #3 by #11 three") || !strings.Contains(out, "\n\nFiled the queued follow-up of #3: #12 the rest\nhttps://github.com/o/r/issues/12\nFiled into the misc manifest #10: it named no --parent.\nIt blocks #3.\nBlocked by #1.") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	if made := issueOf(t, gh, 12); !strings.Contains(made, `"body":"the rest\n\n<!-- se:followup #3 -->\n\n<!-- se:new -->"`) {
		t.Fatal(made)
	}
	if by := linked(t, gh, "repos/o/r/issues/12/dependencies/blocked_by"); !reflect.DeepEqual(by, []int{1}) {
		t.Fatalf("#12 is blocked by %v", by)
	}
	if q := queuedAt(t, d, ws); q != nil {
		t.Fatalf("the queue is left: %+v", q)
	}
}

func TestAQueuedIssueThatWouldBeRefusedRefusesTheSupersedeBeforeItWrites(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	asBox(t)
	d, ws := onFake(t), filepath.FromSlash("/ws")
	// #1 one is open at the top already.
	if code, out, errs := se(t, "issue", "new", "--workspace", ws, "--repo", "o/r", "--title", "one", "--body", "b", "--blocked-by", "none"); code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, _, errs := se(t, "issue", "supersede", "3", "--body", "q", "--workspace", ws, "--repo", "o/r")
	if code != 1 || !strings.Contains(errs, `the issue this box queued, "one", would be refused, so nothing was done: #1 is an open se issue titled "one"`) || !strings.Contains(errs, "se issue new --replace") {
		t.Fatalf("exit %d, %q", code, errs)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused supersede wrote %q", w)
	}
	if q := queuedAt(t, d, ws); len(q) != 1 {
		t.Fatalf("queued %+v", q)
	}
}

// boxCheckout is a box's checkout ws of issue-6, its origin a bare
// repository; main holds the commit fix, and GitHub holds open leaf #6. It
// answers the landing answers file, every question answered.
func boxCheckout(t *testing.T) (ws, answers, fix string, d *disk.Fake, gh *github.Fake) {
	t.Helper()
	root := t.TempDir()
	origin := filepath.Join(root, "origin.git")
	ws = filepath.Join(root, "ws")
	git := func(dir string, args ...string) string {
		t.Helper()
		out, err := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t"}, args...)...).CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	git(root, "init", "-q", "--bare", "-b", "main", origin)
	git(root, "clone", "-q", origin, ws)
	git(ws, "checkout", "-q", "-b", "main")
	git(ws, "commit", "-q", "--allow-empty", "-m", "the fix")
	fix = git(ws, "rev-parse", "HEAD")
	git(ws, "push", "-q", "origin", "main")
	git(ws, "checkout", "-q", "-b", "issue-6")
	git(ws, "commit", "-q", "--allow-empty", "-m", "work")
	spec, err := os.ReadFile(filepath.Join("..", "..", "..", issues.QuestionsFile))
	if err != nil {
		t.Fatal(err)
	}
	d = onFake(t)
	put(t, d, filepath.Join(ws, issues.QuestionsFile), string(spec))
	qs, err := issues.Questions(d, ws)
	if err != nil {
		t.Fatal(err)
	}
	all := ""
	for _, q := range qs {
		all += q.Key + ": none\n"
	}
	answers = filepath.Join(root, "answers.yaml")
	put(t, d, answers, all)
	// The check records the tree it passed, as tests/check.sh does.
	worldOf(t).Check = func(procs proc.Procs, dir string) error {
		tree, err := battery.Tree(procs, dir)
		if err == nil {
			_, err = battery.Pass(d, procs, dir, tree)
		}
		return err
	}
	gh = hubAt(t, map[string]string{
		"repos/o/r/issues/6": `{"number":6,"title":"six","state":"open"}`,
		"repos/o/r/activity?ref=refs/heads/issue-6&activity_type=branch_creation&per_page=100": `[]`,
	})
	return ws, answers, fix, d, gh
}

func TestALandFilesTheQueuedIssueAfterItsPR(t *testing.T) {
	t.Parallel()
	ws, answers, _, d, gh := boxCheckout(t)
	asBox(t)
	if code, out, errs := se(t, "issue", "new", "--workspace", ws, "--repo", "o/r", "--title", "left", "--body", "b", "--blocked-by", "6"); code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, out, errs := se(t, "issue", "land", "--json", "--answers", answers, "--workspace", ws, "--repo", "o/r")
	// The PR is #7, the follow-up #9, blocked by #6 until it merges, in the
	// misc manifest #8 it opened.
	if code != 0 || !strings.HasPrefix(out, `{"issue":6,"number":7,`) || !strings.Contains(out, `"filed":[{"number":9,"url":"https://github.com/o/r/issues/9","blocked_by":[6],"parent":8,"misc":true}]`) {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	if made := issueOf(t, gh, 9); !strings.Contains(made, `<!-- se:followup #6 -->`) {
		t.Fatal(made)
	}
	// The queue is filed once: the next land files nothing.
	if q := queuedAt(t, d, ws); q != nil {
		t.Fatalf("the queue is left: %+v", q)
	}
	code, out, _ = se(t, "issue", "land", "--answers", answers, "--workspace", ws, "--repo", "o/r")
	if code != 0 || strings.Contains(out, "Filed") {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestACloseFilesTheQueuedIssueAfterItCloses(t *testing.T) {
	t.Parallel()
	ws, answers, fix, d, gh := boxCheckout(t)
	asBox(t)
	if code, out, errs := se(t, "issue", "new", "--workspace", ws, "--repo", "o/r", "--title", "left", "--body", "b", "--blocked-by", "none", "--person"); code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	code, out, errs := se(t, "issue", "close", "6", "--fixed-by", fix, "--answers", answers, "--workspace", ws, "--repo", "o/r")
	if code != 0 || !strings.HasPrefix(out, "Closed #6: its work is on main") || !strings.Contains(out, "Filed the queued follow-up of #6: #7 left\nhttps://github.com/o/r/issues/7\nFor a person: labelled se-person") {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	if made := issueOf(t, gh, 7); !strings.Contains(made, `<!-- se:followup #6 -->`) || !strings.Contains(made, `{"name":"se-person"}`) {
		t.Fatal(made)
	}
	if q := queuedAt(t, d, ws); q != nil {
		t.Fatalf("the queue is left: %+v", q)
	}
}
