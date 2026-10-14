// Internal test package: it drives the unexported autoMerge.
package issues

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"

	"github.com/mb-89/SE/src/internal/battery"
)

const (
	pullsPath = "repos/o/r/pulls?head=o:issue-6&base=main&state=open&per_page=100"
	pr14      = `{"number":14,"node_id":"PR_14","html_url":"https://github.com/o/r/pull/14"}`
	issue6    = "repos/o/r/issues/6"
	leaf6     = `{"number":6,"title":"the work","sub_issues_summary":{"total":0,"completed":0}}`
	comments6 = "repos/o/r/issues/6/comments?per_page=100"
	post6     = "repos/o/r/issues/6/comments"
	created6  = "repos/o/r/activity?ref=refs/heads/issue-6&activity_type=branch_creation&per_page=100"
)

// qs and full are a short list of landing questions and an answer to each.
var (
	qs   = []Question{{Key: "done", Question: "What does it deliver?"}, {Key: "left", Question: "What is left?"}}
	full = map[string]string{"done": "the landing", "left": "nothing"}
)

// landGH answers land's gh calls by path, fails those in fail, and keeps
// every call it was asked.
func landGH(t *testing.T, answers map[string]string, fail map[string]string) (GH, *[][]string) {
	t.Helper()
	for path, a := range map[string]string{issue6: leaf6, comments6: `[]`, post6: `{}`, created6: `[{"timestamp":"2026-01-02T10:00:00Z"}]`} {
		if _, ok := answers[path]; !ok {
			answers[path] = a
		}
	}
	var calls [][]string
	return func(args ...string) ([]byte, error) {
		calls = append(calls, args)
		path := args[len(args)-1]
		if msg, ok := fail[path]; ok {
			return nil, errors.New(msg)
		}
		a, ok := answers[path]
		if !ok {
			t.Fatalf("gh %v was not recorded", args)
		}
		return []byte(a), nil
	}, &calls
}

// claimed is box a on issue-6, claimed from origin's main, with one commit of work.
func claimed(t *testing.T) (origin, a string) {
	t.Helper()
	origin, a, _ = boxes(t)
	if ok, err := Claim(a, 6); err != nil || !ok {
		t.Fatalf("claim: %v %v", ok, err)
	}
	run(t, a, "commit", "-q", "--allow-empty", "-m", "work")
	return origin, a
}

func passes(string) error { return nil }

// landedAt is when the tests land: 90 minutes after landGH's claim.
func landedAt() time.Time { return time.Date(2026, 1, 2, 11, 30, 0, 0, time.UTC) }

func TestLandPushesOpensThePRAndTurnsOnAutoMerge(t *testing.T) {
	origin, a := claimed(t)
	gh, calls := landGH(t, map[string]string{
		pullsPath:         `[]`,
		"repos/o/r/pulls": pr14,
		"graphql":         `{"data":{}}`,
	}, nil)
	l, err := Source{Repo: repo, GH: gh, Clock: clock.NewFake(landedAt())}.Land(a, "", qs, full, passes)
	if err != nil {
		t.Fatal(err)
	}
	if want := (Landing{Issue: 6, Number: 14, URL: "https://github.com/o/r/pull/14", Created: true}); l != want {
		t.Fatalf("%+v", l)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, a, "rev-parse", "HEAD"); got != want {
		t.Fatalf("origin's issue-6 is %s, want %s", got, want)
	}
	body, err := Landed{Issue: 6, Answers: full, Facts: Facts{
		Claimed: time.Date(2026, 1, 2, 10, 0, 0, 0, time.UTC), Landed: landedAt(), Minutes: 90, Commits: 1,
	}}.Comment(qs)
	if err != nil {
		t.Fatal(err)
	}
	want := [][]string{
		{"api", "repos/o/r/issues/6"},
		{"api", "--paginate", comments6},
		{"api", created6},
		{"api", "-X", "POST", "-f", "body=" + body, post6},
		{"api", "--paginate", pullsPath},
		{"api", "-X", "POST", "-f", "title=the work", "-f", "head=issue-6", "-f", "base=main", "-f", "body=Fixes #6", "repos/o/r/pulls"},
		{"api", "-f", "query=" + autoMerge, "-f", "id=PR_14", "graphql"},
	}
	if !reflect.DeepEqual(*calls, want) {
		t.Fatalf("gh calls\n%q\nwant\n%q", *calls, want)
	}
	if !strings.Contains(autoMerge, "mergeMethod: SQUASH") {
		t.Fatal(autoMerge)
	}
}

// profiles is a check that passes and leaves a battery profile, as tests/check.sh does.
func profiles(t *testing.T, p battery.Profile) func(string) error {
	t.Helper()
	return func(dir string) error {
		data, err := json.Marshal(p)
		if err != nil {
			return err
		}
		at := filepath.Join(dir, battery.Dir)
		if err := os.MkdirAll(at, 0o755); err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(at, battery.ProfileFile), data, 0o644)
	}
}

var profile = battery.Profile{
	TotalMs:  1234,
	Steps:    []battery.Step{{Name: "go test", Ms: 1234}},
	Slowest:  []battery.Test{{Package: "p", Name: "TestSlow", Ms: 900}},
	Overruns: []string{"step go test took 1234ms, over its budget of 1000ms"},
}

func TestThePRBodyAndTheLandingFactsShowTheBatteryProfile(t *testing.T) {
	_, a := claimed(t)
	gh, calls := landGH(t, map[string]string{
		pullsPath:         `[]`,
		"repos/o/r/pulls": pr14,
		"graphql":         `{"data":{}}`,
	}, nil)
	if _, err := (Source{Repo: repo, GH: gh, Clock: clock.NewFake(landedAt())}).Land(a, "", qs, full, profiles(t, profile)); err != nil {
		t.Fatal(err)
	}
	var opened, posted string
	for _, c := range *calls {
		switch c[len(c)-1] {
		case "repos/o/r/pulls":
			opened = c[len(c)-2]
		case post6:
			posted = c[len(c)-2]
		}
	}
	if want := "body=Fixes #6\n\n" + profile.Markdown(); opened != want {
		t.Errorf("the PR body is\n%s\nwant\n%s", opened, want)
	}
	for _, want := range []string{"Total: **1234ms**", "| TestSlow | p | 900 |", "**Over budget:** step go test took 1234ms"} {
		if !strings.Contains(opened, want) {
			t.Errorf("the PR body lacks %q", want)
		}
	}
	got, ok, err := ParseLanding(strings.TrimPrefix(posted, "body="))
	if err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	if got.Facts.BatteryMs != 1234 || !reflect.DeepEqual(got.Facts.Slowest, []string{"p TestSlow 900ms"}) ||
		!reflect.DeepEqual(got.Facts.Overruns, profile.Overruns) {
		t.Errorf("facts = %+v", got.Facts)
	}
	if !strings.Contains(posted, "- **over budget:** step go test took 1234ms") {
		t.Errorf("the landing comment does not show the overrun:\n%s", posted)
	}
}

func TestLandAgainUpdatesTheOpenPRsProfile(t *testing.T) {
	_, a := claimed(t)
	gh, calls := landGH(t, map[string]string{pullsPath: `[` + pr14 + `]`, "repos/o/r/pulls/14": pr14, "graphql": `{"data":{}}`}, nil)
	if _, err := (Source{Repo: repo, GH: gh, Clock: atNow()}).Land(a, "", qs, full, profiles(t, profile)); err != nil {
		t.Fatal(err)
	}
	want := []string{"api", "-X", "PATCH", "-f", "body=Fixes #6\n\n" + profile.Markdown(), "repos/o/r/pulls/14"}
	for _, c := range *calls {
		if reflect.DeepEqual(c, want) {
			return
		}
	}
	t.Fatalf("the open PR's body was not updated: %q", *calls)
}

func TestLandAgainPushesAndReportsTheOpenPR(t *testing.T) {
	origin, a := claimed(t)
	run(t, a, "push", "-q", "origin", "HEAD:issue-6")
	run(t, a, "commit", "-q", "--allow-empty", "-m", "fix ci")
	gh, calls := landGH(t, map[string]string{pullsPath: `[` + pr14 + `]`, "graphql": `{"data":{}}`}, nil)
	l, err := Source{Repo: repo, GH: gh, Clock: atNow()}.Land(a, "", qs, full, passes)
	if err != nil || l.Created || l.Number != 14 {
		t.Fatalf("%+v %v", l, err)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, a, "rev-parse", "HEAD"); got != want {
		t.Fatalf("origin's issue-6 is %s, want %s", got, want)
	}
	for _, c := range *calls {
		if c[len(c)-1] == "repos/o/r/pulls" {
			t.Fatalf("opened a second PR: %v", c)
		}
	}
}

func TestLandMergesAPRWithNothingToWaitFor(t *testing.T) {
	_, a := claimed(t)
	gh, calls := landGH(t, map[string]string{
		pullsPath:                  `[` + pr14 + `]`,
		"repos/o/r/pulls/14/merge": `{"merged":true}`,
	}, map[string]string{"graphql": "gh: Pull request Pull request is in clean status (enablePullRequestAutoMerge)"})
	l, err := Source{Repo: repo, GH: gh, Clock: atNow()}.Land(a, "", qs, full, passes)
	if err != nil || !l.Merged {
		t.Fatalf("%+v %v", l, err)
	}
	last := (*calls)[len(*calls)-1]
	if want := []string{"api", "-X", "PUT", "-f", "merge_method=squash", "repos/o/r/pulls/14/merge"}; !reflect.DeepEqual(last, want) {
		t.Fatalf("%q", last)
	}
}

func TestLandTurnsOnAutoMergeWhereGraphQLIsRefused(t *testing.T) {
	_, a := claimed(t)
	gh, calls := landGH(t, map[string]string{
		pullsPath:                           `[` + pr14 + `]`,
		"repos/o/r/pulls/14/ccr/auto_merge": `{"enabled":true,"merge_method":"squash"}`,
	}, map[string]string{"graphql": "gh: GitHub GraphQL is not available from Claude Code sessions; use the REST API (HTTP 403)"})
	l, err := Source{Repo: repo, GH: gh, Clock: atNow()}.Land(a, "", qs, full, passes)
	if err != nil || l.Merged || l.Number != 14 {
		t.Fatalf("%+v %v", l, err)
	}
	last := (*calls)[len(*calls)-1]
	if want := []string{"api", "-X", "PUT", "-f", "merge_method=squash", "repos/o/r/pulls/14/ccr/auto_merge"}; !reflect.DeepEqual(last, want) {
		t.Fatalf("%q", last)
	}
}

func TestLandSaysWhenAutoMergeFails(t *testing.T) {
	_, a := claimed(t)
	gh, _ := landGH(t, map[string]string{pullsPath: `[` + pr14 + `]`}, map[string]string{"graphql": "gh: auto-merge is not allowed"})
	if _, err := (Source{Repo: repo, GH: gh, Clock: atNow()}).Land(a, "", qs, full, passes); err == nil || !strings.Contains(err.Error(), "PR #14") || !strings.Contains(err.Error(), "auto-merge is not on") {
		t.Fatalf("%v", err)
	}
}

func TestLandRefusesBeforePushing(t *testing.T) {
	origin, a := claimed(t)
	// It reads the issue, and nothing else.
	never := func(t *testing.T) GH {
		return func(args ...string) ([]byte, error) {
			if reflect.DeepEqual(args, []string{"api", issue6}) {
				return []byte(leaf6), nil
			}
			t.Fatalf("gh %v after a refusal", args)
			return nil, nil
		}
	}
	fails := func(string) error { return errors.New("go test: FAIL") }
	if _, err := (Source{Repo: repo, GH: never(t), Clock: atNow()}).Land(a, "", qs, full, fails); err == nil || !strings.Contains(err.Error(), "nothing was pushed: go test: FAIL") {
		t.Fatalf("%v", err)
	}
	if err := os.WriteFile(filepath.Join(a, "x"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	checked := false
	if _, err := (Source{Repo: repo, GH: never(t), Clock: atNow()}).Land(a, "", qs, full, func(string) error { checked = true; return nil }); err == nil || !strings.Contains(err.Error(), "not committed") || checked {
		t.Fatalf("%v, checked %v", err, checked)
	}
	run(t, a, "stash", "-u", "-q")
	run(t, a, "checkout", "-q", "main")
	if _, err := (Source{Repo: repo, GH: never(t), Clock: atNow()}).Land(a, "", qs, full, passes); err == nil || !strings.Contains(err.Error(), "issue-<n> branch") {
		t.Fatalf("%v", err)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, origin, "rev-parse", "main"); got != want {
		t.Fatalf("a refused land moved issue-6 to %s", got)
	}
}

func TestLandRefusesAParent(t *testing.T) {
	origin, a := claimed(t)
	gh, calls := landGH(t, map[string]string{issue6: `{"number":6,"title":"the tree","sub_issues_summary":{"total":2,"completed":1}}`}, nil)
	checked := false
	_, err := Source{Repo: repo, GH: gh, Clock: atNow()}.Land(a, "", qs, full, func(string) error { checked = true; return nil })
	if err == nil || !strings.Contains(err.Error(), "a parent holds no work") || checked {
		t.Fatalf("%v, checked %v", err, checked)
	}
	if len(*calls) != 1 {
		t.Fatalf("%q", *calls)
	}
	if got, want := run(t, origin, "rev-parse", "issue-6"), run(t, origin, "rev-parse", "main"); got != want {
		t.Fatalf("a refused land moved issue-6 to %s", got)
	}
}
