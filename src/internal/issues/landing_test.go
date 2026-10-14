// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"encoding/json"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
)

func TestTheLandingQuestionsAreTheSpecsList(t *testing.T) {
	t.Parallel()
	// The spec is the checkout's own file, so it is read from the real disk.
	got, err := Questions(disk.Real(), filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	var keys []string
	for _, q := range got {
		keys = append(keys, q.Key)
		if q.Hint == "" {
			t.Errorf("%s has no hint", q.Key)
		}
	}
	want := []string{"done", "timeline", "decided", "well", "cost", "by-hand", "rules", "guidance", "lacked", "proof", "left", "doubt", "improve", "else"}
	if !reflect.DeepEqual(keys, want) {
		t.Fatalf("keys %q", keys)
	}
}

func TestLandRefusesAnswersMissingEmptyOrUnknown(t *testing.T) {
	t.Parallel()
	origin, a := claimed(t)
	for _, c := range []struct {
		answers map[string]string
		want    string
	}{
		{map[string]string{"done": "x"}, "missing: left"},
		{nil, "missing: done, left"},
		{map[string]string{"done": "x", "left": " \n"}, "empty: left"},
		{map[string]string{"done": "x", "left": "none", "extra": "y", "also": "z"}, "not in spec/landing.yaml: also, extra"},
	} {
		checked := false
		_, err := Source{Proc: machine, Repo: repo, GitHub: never{t}, Clock: atNow(), Disk: disk.NewFake()}.Land(a, "", qs, c.answers, func(string) error { checked = true; return nil })
		if err == nil || !strings.Contains(err.Error(), c.want) || !strings.Contains(err.Error(), "nothing was pushed") || checked {
			t.Errorf("%v: %v, checked %v", c.answers, err, checked)
		}
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, origin, "rev-parse", "main"); got != want {
		t.Fatalf("a refused land moved issue-6 to %s", got)
	}
}

func TestReadAnswersTakesTextAndRefusesAList(t *testing.T) {
	t.Parallel()
	d := disk.NewFake()
	good, bad := filepath.FromSlash("/good.yaml"), filepath.FromSlash("/bad.yaml")
	for path, text := range map[string]string{good: "done: one line\ntimeline: |\n  first\n  then\nleft:\n", bad: "done:\n  - a\n  - b\n"} {
		if err := d.WriteFile(path, []byte(text)); err != nil {
			t.Fatal(err)
		}
	}
	got, err := ReadAnswers(d, good)
	if want := map[string]string{"done": "one line", "timeline": "first\nthen\n", "left": ""}; err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("%q %v", got, err)
	}
	if _, err := ReadAnswers(d, bad); err == nil || !strings.Contains(err.Error(), "as text") {
		t.Fatalf("%v", err)
	}
}

func TestTheLandingBlockRoundTrips(t *testing.T) {
	t.Parallel()
	l := Landed{Issue: 39, Answers: map[string]string{
		"done": "answers: on the issue, # not a comment",
		"left": "```\nfenced\n```\n- a list in text\n\"quoted\"",
	}, Facts: Facts{
		Claimed: time.Date(2026, 1, 2, 10, 0, 0, 0, time.UTC), Landed: landedAt(), Minutes: 90,
		Commits: 3, Takeovers: 1, MainMerges: 2,
	}}
	body, err := l.Comment(qs)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"**What does it deliver?** (`done`)\nanswers: on the issue", "claim to landing: 1h30m", "main merges: 2", "\n```yaml\n"} {
		if !strings.Contains(body, want) {
			t.Errorf("the comment lacks %q:\n%s", want, body)
		}
	}
	got, ok, err := ParseLanding("Some text above.\n" + body + "\nand below")
	if err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	if !reflect.DeepEqual(got, l) {
		t.Fatalf("round trip\n%+v\nwant\n%+v", got, l)
	}
	if _, ok, err := ParseLanding("Worked by session s."); ok || err != nil {
		t.Fatalf("%v %v", ok, err)
	}
}

func TestLandingFactsCountCommitsMergesAndTakeovers(t *testing.T) {
	t.Parallel()
	_, a := claimed(t)
	// main moves on, and the branch merges it in.
	run(t, a, "checkout", "-q", "main")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "main moves")
	run(t, a, "push", "-q", "origin", "main")
	run(t, a, "checkout", "-q", "issue-6")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "more work")
	run(t, a, "merge", "-q", "--no-ff", "-m", "merge main", "main")
	gh := landGH(t, map[string]string{
		pullsPath: `[` + pr14 + `]`,
		comments6: `[{"id":5,"body":"<!-- se:takeover 1 -->\nTaken over."}]`,
	})
	d := disk.NewFake()
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: clock.NewFake(landedAt()), Disk: d}).Land(a, "", qs, full, battered(d)); err != nil {
		t.Fatal(err)
	}
	c := commentsAt(t, gh, 6)
	posted := c[len(c)-1].Body
	got, ok, err := ParseLanding(posted)
	if err != nil || !ok {
		t.Fatalf("%v %v: %q", ok, err, posted)
	}
	want := Facts{Claimed: time.Date(2026, 1, 2, 10, 0, 0, 0, time.UTC), Landed: landedAt(), Minutes: 90, Commits: 2, Takeovers: 1, MainMerges: 1, Requests: 3}
	if !reflect.DeepEqual(got.Facts, want) || got.Issue != 6 || !reflect.DeepEqual(got.Answers, full) {
		t.Fatalf("%+v", got)
	}
}

func TestLandAgainUpdatesTheLandingComment(t *testing.T) {
	t.Parallel()
	_, a := claimed(t)
	gh := landGH(t, map[string]string{
		pullsPath: `[` + pr14 + `]`,
		comments6: `[{"id":5,"body":"Worked by someone."},{"id":77,"body":"<!-- se:landing -->\nolder answers"}]`,
	})
	d := disk.NewFake()
	if _, err := (Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow(), Disk: d}).Land(a, "", qs, full, battered(d)); err != nil {
		t.Fatal(err)
	}
	patched := 0
	for _, w := range gh.Writes() {
		switch w {
		case "POST repos/o/r/issues/6/comments":
			t.Fatalf("posted a second landing comment: %q", gh.Writes())
		case "PATCH repos/o/r/issues/comments/77":
			patched++
		}
	}
	if c := commentsAt(t, gh, 6); patched != 1 || len(c) != 2 || c[1].ID != 77 || !strings.Contains(c[1].Body, "the landing") {
		t.Fatalf("patched %d times: %q, %+v", patched, gh.Writes(), c)
	}
}

func TestATakeoverRestoresTheAnswersTheLastLandPosted(t *testing.T) {
	t.Parallel()
	answers := map[string]string{
		"done": "answers: on the issue, # not a comment\n #39 too",
		"left": "```\nfenced\n```\n- a list in text\n\"quoted\"",
	}
	older, err := Landed{Issue: 6, Answers: map[string]string{"done": "older", "left": "older"}, Facts: Facts{Landed: landedAt()}}.Comment(qs)
	if err != nil {
		t.Fatal(err)
	}
	latest, err := Landed{Issue: 6, Answers: answers, Facts: Facts{Landed: landedAt()}}.Comment(qs)
	if err != nil {
		t.Fatal(err)
	}
	posted, _ := json.Marshal([]map[string]any{{"id": 1, "body": "Worked by s."}, {"id": 2, "body": older}, {"id": 3, "body": latest}})
	s := Source{Repo: repo, GitHub: recorded(t, map[string]string{comments6: string(posted)}), Disk: disk.NewFake()}
	path := filepath.FromSlash("/w/issue-6-landing.yaml")
	if err := s.Disk.MkdirAll(filepath.Dir(path)); err != nil {
		t.Fatal(err)
	}
	if restored, err := s.RestoreAnswers(6, path); err != nil || !restored {
		t.Fatalf("%v %v", restored, err)
	}
	got, err := ReadAnswers(s.Disk, path)
	if err != nil {
		t.Fatal(err)
	}
	for k, want := range answers {
		if strings.TrimSpace(got[k]) != want {
			t.Errorf("%s: %q, want %q", k, got[k], want)
		}
	}
	if len(got) != len(answers) {
		t.Errorf("%q", got)
	}
	text, _ := s.Disk.ReadFile(path)
	if !strings.HasPrefix(string(text), "# The answers the last land of #6") || strings.Index(string(text), "done:") > strings.Index(string(text), "left:") {
		t.Errorf("the file:\n%s", text)
	}
	// A file the box has already is its own, and is kept.
	if err := s.Disk.WriteFile(path, []byte("done: mine\n")); err != nil {
		t.Fatal(err)
	}
	if restored, err := s.RestoreAnswers(6, path); err != nil || restored {
		t.Fatalf("%v %v", restored, err)
	}
	if text, _ := s.Disk.ReadFile(path); string(text) != "done: mine\n" {
		t.Fatalf("overwrote the box's own answers: %q", text)
	}
	// An issue no land posted answers on writes nothing.
	none := Source{Repo: repo, GitHub: recorded(t, map[string]string{comments6: `[{"id":1,"body":"Worked by s."}]`}), Disk: disk.NewFake()}
	if err := none.Disk.MkdirAll(filepath.Dir(path)); err != nil {
		t.Fatal(err)
	}
	if restored, err := none.RestoreAnswers(6, path); err != nil || restored {
		t.Fatalf("%v %v", restored, err)
	}
	if there, _ := none.Disk.Exists(path); there {
		t.Fatal("wrote answers no land posted")
	}
}

func TestTheAnswersFileStandsBesideTheLeafsCheckout(t *testing.T) {
	t.Parallel()
	ws := filepath.FromSlash("/home/u/SE")
	if got, want := AnswersFile(ws, 6, true), filepath.FromSlash("/home/u/issue-6-landing.yaml"); got != want {
		t.Errorf("worktree: %s, want %s", got, want)
	}
	if got, want := AnswersFile(ws, 6, false), filepath.FromSlash("/home/u/SE-landing.yaml"); got != want {
		t.Errorf("checkout: %s, want %s", got, want)
	}
}
