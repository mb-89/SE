// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
)

func TestTheLandingQuestionsAreTheSpecsList(t *testing.T) {
	got, err := Questions(filepath.Join("..", "..", ".."))
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
	origin, a := claimed(t)
	never := func(args ...string) ([]byte, error) {
		t.Fatalf("gh %v after a refusal", args)
		return nil, nil
	}
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
		_, err := Source{Repo: repo, GH: never, Clock: atNow()}.Land(a, "", qs, c.answers, func(string) error { checked = true; return nil })
		if err == nil || !strings.Contains(err.Error(), c.want) || !strings.Contains(err.Error(), "nothing was pushed") || checked {
			t.Errorf("%v: %v, checked %v", c.answers, err, checked)
		}
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, origin, "rev-parse", "main"); got != want {
		t.Fatalf("a refused land moved issue-6 to %s", got)
	}
}

func TestReadAnswersTakesTextAndRefusesAList(t *testing.T) {
	dir := t.TempDir()
	good, bad := filepath.Join(dir, "good.yaml"), filepath.Join(dir, "bad.yaml")
	for path, text := range map[string]string{good: "done: one line\ntimeline: |\n  first\n  then\nleft:\n", bad: "done:\n  - a\n  - b\n"} {
		if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	got, err := ReadAnswers(good)
	if want := map[string]string{"done": "one line", "timeline": "first\nthen\n", "left": ""}; err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("%q %v", got, err)
	}
	if _, err := ReadAnswers(bad); err == nil || !strings.Contains(err.Error(), "as text") {
		t.Fatalf("%v", err)
	}
}

func TestTheLandingBlockRoundTrips(t *testing.T) {
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
	_, a := claimed(t)
	// main moves on, and the branch merges it in.
	run(t, a, "checkout", "-q", "main")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "main moves")
	run(t, a, "push", "-q", "origin", "main")
	run(t, a, "checkout", "-q", "issue-6")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "more work")
	run(t, a, "merge", "-q", "--no-ff", "-m", "merge main", "main")
	var posted string
	gh, _ := landGH(t, map[string]string{
		pullsPath: `[` + pr14 + `]`,
		"graphql": `{"data":{}}`,
		comments6: `[{"id":5,"body":"<!-- se:takeover 1 -->\nTaken over."}]`,
	}, nil)
	spy := func(args ...string) ([]byte, error) {
		if args[len(args)-1] == post6 {
			posted = strings.TrimPrefix(args[len(args)-2], "body=")
		}
		return gh(args...)
	}
	if _, err := (Source{Repo: repo, GH: spy, Clock: clock.NewFake(landedAt())}).Land(a, "", qs, full, passes); err != nil {
		t.Fatal(err)
	}
	got, ok, err := ParseLanding(posted)
	if err != nil || !ok {
		t.Fatalf("%v %v: %q", ok, err, posted)
	}
	want := Facts{Claimed: time.Date(2026, 1, 2, 10, 0, 0, 0, time.UTC), Landed: landedAt(), Minutes: 90, Commits: 2, Takeovers: 1, MainMerges: 1}
	if !reflect.DeepEqual(got.Facts, want) || got.Issue != 6 || !reflect.DeepEqual(got.Answers, full) {
		t.Fatalf("%+v", got)
	}
}

func TestLandAgainUpdatesTheLandingComment(t *testing.T) {
	_, a := claimed(t)
	gh, calls := landGH(t, map[string]string{
		pullsPath:                      `[` + pr14 + `]`,
		"graphql":                      `{"data":{}}`,
		comments6:                      `[{"id":5,"body":"Worked by someone."},{"id":77,"body":"<!-- se:landing -->\nolder answers"}]`,
		"repos/o/r/issues/comments/77": `{}`,
	}, nil)
	if _, err := (Source{Repo: repo, GH: gh, Clock: atNow()}).Land(a, "", qs, full, passes); err != nil {
		t.Fatal(err)
	}
	patched := 0
	for _, c := range *calls {
		switch c[len(c)-1] {
		case post6:
			t.Fatalf("posted a second landing comment: %q", c)
		case "repos/o/r/issues/comments/77":
			if c[1] != "-X" || c[2] != "PATCH" || !strings.Contains(c[4], "the landing") {
				t.Fatalf("%q", c)
			}
			patched++
		}
	}
	if patched != 1 {
		t.Fatalf("patched %d times: %q", patched, *calls)
	}
}
