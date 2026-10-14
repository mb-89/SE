// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"

	"github.com/mb-89/SE/src/internal/issues"
)

// briefedAt is the clock the recorded briefing is read against.
var briefedAt = time.Date(2026, 10, 13, 12, 0, 0, 0, time.UTC)

// recordedBriefing answers se briefing's gh calls for o/r (and o/probe, read
// as o/r): #3 is ready; #1 is claimed with PR #11, green with auto-merge on;
// #6 waits on a person and holds up #2, which it blocks; #7 is a retro whose
// report waits for the owner. Closed are #20 (landed through PR #21 with its
// answers), #19 (not planned, went to a person on its way), #18 (the last
// retro, three days ago) and the issues of closed, each closed that long ago.
// With person false, nothing waits on a person.
func recordedBriefing(t *testing.T, person bool, closed map[int]time.Duration) {
	t.Helper()
	ago := func(d time.Duration) string { return briefedAt.Add(-d).Format(time.RFC3339) }
	open := []string{
		`{"number":3,"title":"three","state":"open","html_url":"u3"}`,
		`{"number":2,"title":"two","state":"open","html_url":"u2"}`,
		`{"number":1,"title":"one","state":"open","html_url":"u1"}`,
	}
	if person {
		open = append(open,
			`{"number":6,"title":"six","state":"open","html_url":"u6","labels":[{"name":"se"},{"name":"se-person"}]}`,
			`{"number":7,"title":"retro","state":"open","html_url":"u7","labels":[{"name":"se"},{"name":"se-retro"},{"name":"se-person"}]}`)
	}
	shut := []string{
		`{"number":20,"title":"twenty","state":"closed","state_reason":"completed","html_url":"u20","closed_at":"` + ago(time.Hour) + `"}`,
		`{"number":19,"title":"nineteen","state":"closed","state_reason":"not_planned","html_url":"u19","closed_at":"` + ago(2*time.Hour) + `"}`,
		`{"number":18,"title":"a retro","state":"closed","html_url":"u18","closed_at":"` + ago(72*time.Hour) + `","labels":[{"name":"se"},{"name":"se-retro"}]}`,
		`{"number":17,"title":"a PR","state":"closed","html_url":"p17","closed_at":"` + ago(time.Minute) + `","pull_request":{}}`,
	}
	for n, d := range closed {
		shut = append(shut, fmt.Sprintf(`{"number":%d,"title":"closed %d","state":"closed","html_url":"u%d","closed_at":"%s"}`, n, n, n, ago(d)))
	}
	landing, err := issues.Landed{Issue: 20, Answers: map[string]string{"done": "twenty is done"}}.Comment([]issues.Question{{Key: "done", Question: "What?"}})
	if err != nil {
		t.Fatal(err)
	}
	quote := func(s string) string { data, _ := json.Marshal(s); return string(data) }
	answers := map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100":                  "[" + strings.Join(open, ",") + "]",
		"repos/o/r/issues?labels=se&state=closed&per_page=100":                "[" + strings.Join(shut, ",") + "]",
		"repos/o/r/git/matching-refs/heads/issue-":                            `[{"ref":"refs/heads/issue-1","object":{"sha":"s1"}}]`,
		"repos/o/r/pulls?base=main&state=open&per_page=100":                   `[{"number":11,"html_url":"p11","head":{"ref":"issue-1","sha":"s1"}}]`,
		"repos/o/r/pulls/11":                                                  `{"number":11,"html_url":"p11","mergeable":true,"mergeable_state":"clean","auto_merge":{},"head":{"ref":"issue-1","sha":"s1"}}`,
		"repos/o/r/commits/s1/check-runs?per_page=100":                        `{"check_runs":[{"name":"check","status":"completed","conclusion":"success"}]}`,
		"repos/o/r/activity?ref=refs/heads/issue-1&per_page=1":                `[{"timestamp":"` + ago(10*time.Minute) + `"}]`,
		"repos/o/r/issues/6/comments?per_page=100":                            `[{"id":1,"body":"<!-- se:person -->\nneeds the owner's call"}]`,
		"repos/o/r/issues/7/comments?per_page=100":                            `[{"id":2,"body":"<!-- se:person -->\nthe retro report is posted"}]`,
		"repos/o/r/issues/20/comments?per_page=100":                           `[{"id":3,"body":` + quote(landing) + `}]`,
		"repos/o/r/issues/19/comments?per_page=100":                           `[{"id":4,"body":"<!-- se:person -->\nstuck twice"}]`,
		"repos/o/r/issues/18/comments?per_page=100":                           `[{"id":5,"body":"early"},{"id":6,"body":"## Retro report\n- finding one\n- finding two\n<!-- se:retro -->"}]`,
		"repos/o/r/pulls?head=o:issue-20&base=main&state=closed&per_page=100": `[{"number":21,"html_url":"p21","merged_at":"` + ago(time.Hour) + `"}]`,
		"repos/o/r/pulls?head=o:issue-19&base=main&state=closed&per_page=100": `[]`,
	}
	if person {
		answers["repos/o/r/issues/2/dependencies/blocked_by?per_page=100"] = `[{"number":6,"state":"open"}]`
	}
	old, oldClock := gh, wall
	wall = clock.NewFake(briefedAt)
	gh = func(args ...string) ([]byte, error) {
		path := strings.Replace(args[len(args)-1], "repos/o/probe/", "repos/o/r/", 1)
		if a, ok := answers[path]; ok {
			return []byte(a), nil
		}
		// What the record leaves out has nothing: no blockers, no comments, no PR.
		for _, empty := range []string{"/dependencies/blocked_by?", "/comments?", "pulls?head="} {
			if strings.Contains(path, empty) {
				return []byte(`[]`), nil
			}
		}
		return nil, fmt.Errorf("not recorded: %v", args)
	}
	t.Cleanup(func() { gh, wall = old, oldClock })
}

// briefed runs se briefing in a workspace with a README and answers its text.
func briefed(t *testing.T, args ...string) string {
	t.Helper()
	dir := t.TempDir()
	readme := "# SE\n\nReader: a person meeting SE.\n\nSE is a test. It has parts. They talk.\nIt is small. This is cut.\n\n## Install\n"
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte(readme), 0o644); err != nil {
		t.Fatal(err)
	}
	code, out, errs := se(t, append([]string{"briefing", "--workspace", dir}, args...)...)
	if code != 0 {
		t.Fatalf("briefing %v: exit %d, %q %q", args, code, out, errs)
	}
	return out
}

// inOrder fails unless every part is in out, each after the one before.
func inOrder(t *testing.T, out string, parts ...string) {
	t.Helper()
	at := 0
	for _, p := range parts {
		k := strings.Index(out[at:], p)
		if k < 0 {
			t.Fatalf("%q missing, or out of order, in:\n%s", p, out)
		}
		at += k + len(p)
	}
}

func TestTheBriefingTellsEverySectionPendingFirst(t *testing.T) {
	recordedBriefing(t, true, nil)
	out := briefed(t, "--repo", "o/r")
	inOrder(t, out,
		"SE briefing for o/r, 2026-10-13T12:00:00Z",
		"## Waits on you",
		"- #6 six (waiting on a person, holds up 1)", "needs the owner's call", "u6",
		"- #7 retro (waiting on a person, holds up 0)", "the retro report is posted", "u7",
		"## In flight",
		"- #1 one: PR #11 p11; CI green, auto-merge on",
		"fleet check:", "waiting on a person #6", "waiting on a person #7",
		"## What happened (the last 10 closed)",
		"- #20 twenty [PR #21], closed 2026-10-13T11:00:00Z", "twenty is done",
		"- #19 nineteen [not planned, went to a person]",
		"- #18 a retro [retro]",
		"## Last retro", "#18 a retro, closed 2026-10-10T12:00:00Z", "u18", "- finding one", "- finding two",
		"## Next", "se issue next would take #3 three", "u3",
		"1 ready, 1 claimed, 3 blocked, 0 in trees",
		"## What SE is", "SE is a test.\nIt has parts.\nThey talk.\nIt is small.\n",
		"- spec/principles.md: https://github.com/o/r/blob/main/spec/principles.md",
		"- spec/issues.md:", "- CLAUDE.md:")
	if strings.Contains(out, "This is cut") || strings.Contains(out, "a PR") {
		t.Fatalf("the briefing tells more than it should:\n%s", out)
	}
	var b issues.Briefing
	code, js, _ := se(t, "briefing", "--json", "--repo", "o/r")
	if err := json.Unmarshal([]byte(js), &b); code != 0 || err != nil {
		t.Fatalf("exit %d, %q: %v", code, js, err)
	}
	if len(b.Pending) != 2 || b.Pending[0].Holds != 1 || len(b.InFlight) != 1 || b.InFlight[0].PR != 11 ||
		b.Happened[0].Done != "twenty is done" || b.Retro == nil || b.Retro.Number != 18 || b.Next == nil || b.Next.Number != 3 {
		t.Fatalf("%+v", b)
	}
	if r := session(t, "briefing", "--repo", "o/r"); !strings.Contains(r.Text, "## Waits on you") {
		t.Fatalf("the session is not offered the briefing: %+v", r)
	}
}

func TestNothingPendingIsSaidPlainly(t *testing.T) {
	recordedBriefing(t, false, nil)
	out := briefed(t, "--repo", "o/r")
	inOrder(t, out, "## Waits on you\nNothing waits on you.\n", "## In flight", "fleet check: healthy", "2 ready, 1 claimed, 0 blocked")
}

func TestTheWindowIsTheLastDayOrTheLastTenWhicheverAreMore(t *testing.T) {
	// Twelve closed within the day: the day holds more than ten.
	many := map[int]time.Duration{}
	for n := 101; n <= 112; n++ {
		many[n] = time.Duration(n-100) * time.Hour
	}
	recordedBriefing(t, false, many)
	out := briefed(t, "--repo", "o/r")
	inOrder(t, out, "## What happened (closed in the last day)", "#20", "#19", "#111")
	inOrder(t, out, "#112 ", "## Last retro")
	if strings.Contains(out, "#18 a retro [") {
		t.Fatalf("the day's window holds what closed before it:\n%s", out)
	}

	// Four closed within the day: the last ten, which reach back past the retro's.
	few := map[int]time.Duration{}
	for n := 101; n <= 112; n++ {
		few[n] = time.Duration(n-100) * 5 * time.Hour
	}
	recordedBriefing(t, false, few)
	out = briefed(t, "--repo", "o/r")
	inOrder(t, out, "## What happened (the last 10 closed)", "#20", "#19", "#101", "#102", "#103", "#104", "#105", "#106", "#107", "#108", "## Last retro")
	if strings.Contains(out, "#109 ") || strings.Contains(out, "#18 a retro [") {
		t.Fatalf("the last ten hold an eleventh:\n%s", out)
	}

	out = briefed(t, "--repo", "o/r", "--last", "3")
	inOrder(t, out, "## What happened (the last 3 closed)", "#20", "#19", "#101", "## Last retro")
	if strings.Contains(out, "#102 ") {
		t.Fatalf("--last 3 holds a fourth:\n%s", out)
	}

	for _, since := range []string{"2026-10-13T00:30:00Z", "11h30m", "2026-10-13"} {
		out = briefed(t, "--repo", "o/r", "--since", since)
		if strings.Contains(out, "#103 ") || !strings.Contains(out, "#102 ") {
			t.Fatalf("--since %s:\n%s", since, out)
		}
	}
	out = briefed(t, "--repo", "o/r", "--since", "3d")
	inOrder(t, out, "## What happened (closed since 2026-10-10T12:00:00Z)", "#18 a retro [retro]")

	for _, bad := range [][]string{{"--since", "1d", "--last", "2"}, {"--last", "-1"}, {"--since", "soon"}} {
		if code, _, _ := se(t, append([]string{"briefing", "--repo", "o/r"}, bad...)...); code == 0 {
			t.Fatalf("briefing %v was not refused", bad)
		}
	}
}

// probe registers the test's pending source once, however often it runs.
var probe sync.Once

func TestAPendingSourceRegistersItself(t *testing.T) {
	recordedBriefing(t, false, nil)
	probe.Do(func() {
		issues.RegisterPending(issues.PendingSource{Name: "probe", List: func(o issues.Open) ([]issues.Pending, error) {
			if o.Repo != "o/probe" {
				return nil, nil
			}
			return []issues.Pending{{Number: 99, Title: "a probe", URL: "u99", Reason: "probing"}}, nil
		}})
	})
	inOrder(t, briefed(t, "--repo", "o/probe"), "## Waits on you\n- #99 a probe (probe, holds up 0)\n  probing\n  u99\n", "## In flight")
	if out := briefed(t, "--repo", "o/r"); !strings.Contains(out, "Nothing waits on you.") {
		t.Fatalf("the probe answered for another repository:\n%s", out)
	}
}
