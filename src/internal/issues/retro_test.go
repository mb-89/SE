// Internal test package: it uses the package's recorded-gh fakes and unexported parts.
package issues

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/github"
)

// rqs are the landing questions the retro tests read.
var rqs = []Question{{Key: "done", Question: "What does it deliver?"}, {Key: "by-hand", Question: "What did you do by hand?"}}

var (
	prevClosed = time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)
	since      = "&since=2026-10-01T00:00:00Z"
)

func closedJSON(n int, reason, closed, body string, extra string) string {
	return fmt.Sprintf(`{"number":%d,"title":"t%d","state":"closed","state_reason":%q,"closed_at":%q,"body":%q,"labels":[{"name":"se"}]%s}`, n, n, reason, closed, body, extra)
}

func landing(t *testing.T, n int, answers map[string]string, claimed time.Time) string {
	t.Helper()
	body, err := Landed{Issue: n, Answers: answers, Facts: Facts{Claimed: claimed, Landed: claimed.Add(time.Hour), Requests: 40, RateLimits: 3, RateLimitWaitS: 90 * 60}}.Comment(rqs)
	if err != nil {
		t.Fatal(err)
	}
	return body
}

func jsonComments(bodies ...string) string {
	var parts []string
	for k, b := range bodies {
		parts = append(parts, fmt.Sprintf(`{"id":%d,"body":%q,"created_at":"2026-10-0%dT00:00:00Z"}`, 100+k, b, k+2))
	}
	return "[" + strings.Join(parts, ",") + "]"
}

// previousReport is retro #20's report: one finding on the fixes check, one
// on a metric, one that made no issue.
func previousReport(t *testing.T) string {
	t.Helper()
	text, err := RetroReport{
		Retro: 20, Attended: true, Window: RetroWindow{Until: prevClosed},
		Metrics: Metrics{"closed": 2, "conflicts": 1, "conflicts_per_issue": 0.5, "ci_reruns_per_issue": 0},
		Findings: []Lesson{
			{Title: "PRs without Fixes", Class: "landing", Body: "b", Home: "check", Check: "fixes", Issue: 21},
			{Title: "Conflicts", Class: "merging", Body: "b", Home: "gate", Metric: "conflicts_per_issue", Issue: 22},
			{Title: "Kept as is", Class: "merging", Body: "b", Home: "guidance"},
		},
		Classes:  []Class{{"landing", "a check"}, {"merging", "a gate"}},
		WentWell: []string{"fan-out"},
	}.assemble("## The window\nold facts")
	if err != nil {
		t.Fatal(err)
	}
	return text
}

// retroRepo records o/r with retro #30 open. later says whether retro #20
// closed before it; then the window opens at its closing.
func retroRepo(t *testing.T, later bool, body string) map[string]string {
	t.Helper()
	at := func(day, hour int) string {
		return time.Date(2026, 10, day, hour, 0, 0, 0, time.UTC).Format(time.RFC3339)
	}
	a := map[string]string{
		"repos/o/r/issues/30":                                        fmt.Sprintf(`{"number":30,"title":"SE retro","state":"open","html_url":"u30","body":%q,"labels":[{"name":"se"},{"name":"se-retro"}]}`, body),
		"repos/o/r/issues/30/comments?per_page=100":                  `[]`,
		"repos/o/r/issues?labels=se-retro&state=closed&per_page=100": `[]`,
		"repos/o/r/pulls?state=closed&base=main&per_page=100": `[` +
			`{"number":49,"body":"Fixes #19","merged_at":"2026-09-29T00:00:00Z","merge_commit_sha":"m49","head":{"sha":"h49"}},` +
			`{"number":50,"title":"fifty","body":"Fixes #23","merged_at":"2026-10-02T11:30:00Z","merge_commit_sha":"m50","head":{"sha":"h50"}},` +
			`{"number":51,"title":"fifty-one","body":"for #24","merged_at":"` + at(3, 9) + `","merge_commit_sha":"m51","head":{"sha":"h51"}},` +
			`{"number":52,"title":"closed","body":"Fixes #25","merged_at":null},` +
			// The PRs that brought the rule checks; #91 brought the mark.
			`{"number":14,"title":"land","body":"Fixes #6","merged_at":"2026-09-01T00:00:00Z","merge_commit_sha":"m14","head":{"sha":"h14"}},` +
			`{"number":74,"title":"answers","body":"Fixes #39","merged_at":"2026-09-01T00:00:00Z","merge_commit_sha":"m74","head":{"sha":"h74"}},` +
			`{"number":91,"title":"retro","body":"Fixes #40","merged_at":"2026-10-03T10:30:00Z","merge_commit_sha":"m91","head":{"sha":"h91"}}]`,
		"repos/o/r/commits/h91/check-runs?filter=all&per_page=100": `{"check_runs":[{"id":7,"name":"check","status":"completed","conclusion":"success"}]}`,
		"repos/o/r/pulls/91/files?per_page=100":                    `[]`,
		"repos/o/r/commits/h50/check-runs?filter=all&per_page=100": `{"check_runs":[{"id":1,"name":"check","status":"completed","conclusion":"failure"},{"id":2,"name":"check","status":"completed","conclusion":"success"}]}`,
		"repos/o/r/commits/h51/check-runs?filter=all&per_page=100": `{"check_runs":[{"id":3,"name":"check","status":"completed","conclusion":"failure"}]}`,
		"repos/o/r/pulls/50/files?per_page=100":                    `[{"filename":"src/scripts/check-claims.sh","status":"added","patch":"@@ -0,0 +1,3 @@\n+#!/bin/sh\n+# Lists claims with no PR, since fleet check had no such view.\n+gh api x"},{"filename":"src/x.go","status":"added"}]`,
		"repos/o/r/pulls/51/files?per_page=100":                    `[]`,
		"repos/o/r/issues/23/comments?per_page=100": jsonComments(
			"<!-- se:takeover 1 -->\n<!-- se:takeover-head abc -->\nTaken over.",
			landing(t, 23, map[string]string{"done": "it works", "by-hand": "wrote src/scripts/check-claims.sh"}, time.Date(2026, 10, 2, 10, 0, 0, 0, time.UTC))),
		"repos/o/r/issues/24/comments?per_page=100": jsonComments("<!-- se:person -->\nStuck twice."),
		"repos/o/r/issues/25/comments?per_page=100": `[]`,
		"repos/o/r/issues/26/comments?per_page=100": `[]`,
	}
	// #31 and #32 hold #24 back, #33 holds #23 back; #34 holds #24 too, but
	// before the window, and #35 is no hold: one hold minted again.
	person := `[` +
		`{"number":31,"title":"Decide how #24 goes on: t24","created_at":"` + at(2, 1) + `"},` +
		`{"number":32,"title":"Decide how #24 goes on: t24","created_at":"` + at(2, 2) + `"},` +
		`{"number":33,"title":"Decide how #23 goes on: t23","created_at":"` + at(2, 3) + `"},` +
		`{"number":34,"title":"Decide how #24 goes on: t24","created_at":"2026-09-20T00:00:00Z"},` +
		`{"number":35,"title":"Set up a token","created_at":"` + at(2, 4) + `"}]`
	closed := []string{
		closedJSON(23, "completed", at(2, 12), "work\n\n"+NewMark, ""),
		// The mark is bounded by creation, #91 brought it at 10:30 on the 3rd:
		// #24 and #26 lack it but were made before, #25 lacks it and was made after.
		closedJSON(24, "completed", at(3, 10), "by hand", `,"created_at":"`+at(2, 0)+`"`),
		closedJSON(25, "duplicate", at(3, 11), "by hand", `,"created_at":"2026-10-03T10:45:00Z"`),
		closedJSON(26, "completed", at(3, 12), "by hand", `,"created_at":"`+at(2, 0)+`","sub_issues_summary":{"total":2,"completed":2}`),
	}
	commits := `[{"sha":"x99","commit":{"message":"pushed straight\n\nto main"}},{"sha":"m51","commit":{"message":"m"}},{"sha":"m50","commit":{"message":"m"}}]`
	if !later {
		closed = append(closed, closedJSON(19, "completed", "2026-09-29T00:00:00Z", NewMark, ""))
		a["repos/o/r/issues/19/comments?per_page=100"] = jsonComments(landing(t, 19, map[string]string{"done": "old", "by-hand": "none"}, time.Date(2026, 9, 28, 0, 0, 0, 0, time.UTC)))
		a["repos/o/r/commits/h49/check-runs?filter=all&per_page=100"] = `{"check_runs":[{"id":9,"name":"check","status":"completed","conclusion":"success"}]}`
		a["repos/o/r/pulls/49/files?per_page=100"] = `[]`
		for _, n := range []int{14, 74} {
			a[fmt.Sprintf("repos/o/r/commits/h%d/check-runs?filter=all&per_page=100", n)] = `{"check_runs":[{"id":8,"name":"check","status":"completed","conclusion":"success"}]}`
			a[fmt.Sprintf("repos/o/r/pulls/%d/files?per_page=100", n)] = `[]`
		}
		a["repos/o/r/issues?labels=se&state=closed&per_page=100"] = "[" + strings.Join(closed, ",") + "]"
		a["repos/o/r/issues?labels=se-person&state=all&per_page=100"] = person
		a["repos/o/r/commits?sha=main&per_page=100&until=2026-10-13T12:00:00Z"] = commits[:len(commits)-1] + `,{"sha":"m49","commit":{"message":"m"}},{"sha":"first","commit":{"message":"the first commit"}}]`
		return a
	}
	// GitHub's since is about updates: #19 closed before the window but was
	// touched after it, so the list holds it and the window leaves it out.
	closed = append(closed, closedJSON(19, "completed", "2026-09-29T00:00:00Z", NewMark, ""))
	a["repos/o/r/issues?labels=se-retro&state=closed&per_page=100"] = `[{"number":10,"state":"closed","closed_at":"2026-09-01T00:00:00Z"},{"number":20,"state":"closed","closed_at":"2026-10-01T00:00:00Z"}]`
	a["repos/o/r/issues/10/comments?per_page=100"] = `[]`
	a["repos/o/r/issues/20/comments?per_page=100"] = jsonComments(previousReport(t))
	a["repos/o/r/issues/21"] = `{"number":21,"state":"closed","state_reason":"completed"}`
	a["repos/o/r/issues/22"] = `{"number":22,"state":"open"}`
	a["repos/o/r/issues?labels=se&state=closed&per_page=100"+since] = "[" + strings.Join(closed, ",") + "]"
	a["repos/o/r/issues?labels=se-person&state=all&per_page=100"+since] = person
	a["repos/o/r/commits?sha=main&per_page=100"+since+"&until=2026-10-13T12:00:00Z"] = commits
	return a
}

func collect(t *testing.T, later bool) Collected {
	t.Helper()
	gh := recorded(t, retroRepo(t, later, "<!-- se:retro attended -->"))
	c, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Collect(30)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func rows(c Collected) []int {
	var ns []int
	for _, r := range c.Rows {
		ns = append(ns, r.Number)
	}
	return ns
}

func TestTheFirstRetroCoversTheWholeHistory(t *testing.T) {
	t.Parallel()
	c := collect(t, false)
	if c.Window.Previous != 0 || !c.Window.Since.IsZero() || !c.Window.Until.Equal(now) || !c.Attended {
		t.Fatalf("%+v", c.Window)
	}
	if got := rows(c); !reflect.DeepEqual(got, []int{19, 23, 24, 25, 26}) || c.PRs != 6 || c.Commits != 5 {
		t.Fatalf("rows %v, %d PRs, %d commits", got, c.PRs, c.Commits)
	}
	if c.Previous != nil || c.Score != nil || len(c.History) != 0 {
		t.Fatalf("a first retro scores nothing: %+v %+v", c.Previous, c.Score)
	}
}

func TestALaterRetroCoversWhatClosedSinceTheLastOne(t *testing.T) {
	t.Parallel()
	c := collect(t, true)
	if c.Window.Previous != 20 || !c.Window.Since.Equal(prevClosed) {
		t.Fatalf("%+v", c.Window)
	}
	if got := rows(c); !reflect.DeepEqual(got, []int{23, 24, 25, 26}) || c.PRs != 3 || c.Commits != 3 {
		t.Fatalf("rows %v, %d PRs, %d commits", got, c.PRs, c.Commits)
	}
}

func TestEachRuleCheck(t *testing.T) {
	t.Parallel()
	c := collect(t, true)
	var got []string
	for _, x := range c.Checks {
		got = append(got, x.Kind+" "+x.Subject)
	}
	want := []string{
		"fixes PR #51",          // its body names no Fixes #n
		"ci PR #51",             // its last run failed; #50's rerun passed
		"outside-pr commit x99", // no merged PR made it
		"mark #25",              // made after #91 brought the mark, and lacks it
		"answers #24",           // completed leaf, no answers; #25 a duplicate, #26 a parent
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("%q", got)
	}
	// #24 and #26 lack the mark, but were made before #91 brought it: a count,
	// not a check, though #26 closed after it.
	if want := map[string]int{"mark": 2}; !reflect.DeepEqual(c.Before, want) {
		t.Fatalf("before %v", c.Before)
	}
	draft, err := c.Draft(rqs)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(draft, "(`mark`): broken once. Before the rule came with PR #91: broken 2 times, not counted.\n") {
		t.Fatalf("the draft lacks the count before the mark:\n%s", draft)
	}
	if !strings.Contains(c.Checks[1].What, "check failure") || !strings.Contains(c.Checks[2].What, "pushed straight:") {
		t.Fatalf("%+v", c.Checks)
	}
}

func TestTheAnswersCheckSkipsWhatLandsNoBranch(t *testing.T) {
	t.Parallel()
	a := retroRepo(t, true, "<!-- se:retro attended -->")
	key := "repos/o/r/issues?labels=se&state=closed&per_page=100" + since
	at := time.Date(2026, 10, 4, 0, 0, 0, 0, time.UTC).Format(time.RFC3339)
	person := closedJSON(27, "completed", at, NewMark, "")
	person = strings.Replace(person, `[{"name":"se"}]`, `[{"name":"se"},{"name":"se-person"}]`, 1)
	overhaul := closedJSON(28, "completed", at, NewMark, "")
	overhaul = strings.Replace(overhaul, `[{"name":"se"}]`, `[{"name":"se"},{"name":"se-overhaul"}]`, 1)
	a[key] = strings.TrimSuffix(a[key], "]") + "," + person + "," + overhaul + "]"
	a["repos/o/r/issues/27/comments?per_page=100"] = `[]`
	a["repos/o/r/issues/28/comments?per_page=100"] = `[]`
	c, err := Source{Proc: machine, Repo: repo, GitHub: recorded(t, a), Clock: atNow()}.Collect(30)
	if err != nil {
		t.Fatal(err)
	}
	if got := rows(c); !reflect.DeepEqual(got, []int{23, 24, 25, 26, 27, 28}) {
		t.Fatalf("rows %v", got)
	}
	for _, x := range c.Checks {
		if x.Kind == "answers" && x.Subject != "#24" {
			t.Fatalf("a person's decision or an overhaul broke the answers check: %+v", x)
		}
	}
	// The per-issue metrics divide by the landed issues, #23 and #24, as
	// before: closing a person's decision and an overhaul dilutes nothing.
	if m := c.Metrics; m["closed"] != 6 || m["landed"] != 2 || m["for_person"] != 1 || m["conflicts_per_issue"] != 0.5 {
		t.Fatalf("%v", m)
	}
}

func TestTheCountsAndScripts(t *testing.T) {
	t.Parallel()
	c := collect(t, true)
	want := Metrics{
		"closed": 4, "landed": 2, "for_person": 0, "conflicts": 1, "takeovers": 1, "ci_reruns": 1, "person_flags": 1, "by_hand": 1, "duplicates": 2, "requests": 40, "rate_limits": 3, "rate_limit_minutes": 90,
		"conflicts_per_issue": 0.5, "takeovers_per_issue": 0.5, "ci_reruns_per_issue": 0.5, "person_flags_per_issue": 0.5, "by_hand_per_issue": 0.5, "duplicates_per_issue": 1, "requests_per_issue": 20, "rate_limits_per_issue": 1.5, "rate_limit_minutes_per_issue": 45,
		"claim_to_merge_minutes": 90,
	}
	if !reflect.DeepEqual(c.Metrics, want) {
		t.Fatalf("%v", c.Metrics)
	}
	// The draft shows the fleet's GitHub requests, and the rate-limit
	// refusals and minutes waited for the reset, per landed issue, from the
	// landing facts, and what the closed issues were.
	draft, err := c.Draft(rqs)
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range []string{
		"| requests | 40 | 20 |", "GitHub requests: 20 per landed issue, counted by the landing facts of 1 of the 4 closed issues.",
		"Of the closed issues, 2 landed (the ones the answers check counts, which the per-issue metrics divide by) and 0 were for a person.",
		"| rate_limits | 3 | 1.5 |", "| rate_limit_minutes | 90 | 45 |",
		"GitHub rate limits: 1.5 refusals and 45 minutes waited for the reset per landed issue; 1 of the 4 closed issues met one.",
	} {
		if !strings.Contains(draft, line) {
			t.Errorf("the draft does not say %q:\n%s", line, draft)
		}
	}
	if want := []Script{{"src/scripts/check-claims.sh", 50, "Lists claims with no PR, since fleet check had no such view.", "check"}}; !reflect.DeepEqual(c.Scripts, want) {
		t.Fatalf("%+v", c.Scripts)
	}
}

func TestTheMatrixReadsEveryLandingAnswer(t *testing.T) {
	t.Parallel()
	c := collect(t, false)
	draft, err := c.Draft(rqs)
	if err != nil {
		t.Fatal(err)
	}
	_, matrix, _ := strings.Cut(draft, matrixMark)
	for _, want := range []string{
		"No landing answers: #24, #25, #26.",
		"### `done`: What does it deliver?\n- #19 t19 (closed by merged PR #49): old\n- #23 t23 (closed by merged PR #50): it works\n",
		// #19's by-hand answer is none, so it is left out.
		"### `by-hand`: What did you do by hand?\n- #23 t23 (closed by merged PR #50): wrote src/scripts/check-claims.sh\n",
	} {
		if !strings.Contains(matrix, want) {
			t.Errorf("the matrix lacks %q:\n%s", want, matrix)
		}
	}
	r, facts, err := ParseReport(draft)
	if err != nil || r.Retro != 30 || len(r.Checks) != len(c.Checks) || !strings.HasPrefix(facts, "## The window") || strings.Contains(facts, "The matrix") {
		t.Fatalf("%+v %q %v", r, facts, err)
	}
}

// Each row says how its issue closed, so the matrix can head its answers
// with it: an issue closed with no merged PR answered for a branch, not main.
func TestARowSaysHowItsIssueClosed(t *testing.T) {
	t.Parallel()
	answered := landing(t, 0, map[string]string{"done": "on a branch", "by-hand": "none"}, time.Date(2026, 10, 2, 10, 0, 0, 0, time.UTC))
	gh := recorded(t, map[string]string{
		"repos/o/r/issues/1/comments?per_page=100": jsonComments(answered),
		"repos/o/r/issues/2/comments?per_page=100": jsonComments(answered, fmt.Sprintf(fixedMark+"\nClosed.", "4957ced7aaaabbbbccccdddd")),
		"repos/o/r/issues/3/comments?per_page=100": jsonComments(answered),
		"repos/o/r/issues/4/comments?per_page=100": `[]`,
	})
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	at := time.Date(2026, 10, 2, 11, 0, 0, 0, time.UTC)
	fixedBy := map[int]merged{1: {Number: 9, MergedAt: &at}}
	for n, want := range map[int]string{
		1: "by merged PR #9",
		2: "as fixed by 4957ced, no merged PR of its own",
		3: "as a duplicate, no merged PR of its own",
		4: "as a person's decision, no merged PR of its own",
	} {
		reason := map[int]string{3: "duplicate", 4: "not_planned"}[n]
		if reason == "" {
			reason = "completed"
		}
		r, _, err := s.row(past{issue: issue{Number: n, Title: "t", StateReason: reason}}, fixedBy)
		if err != nil || r.Closed != want {
			t.Errorf("#%d closed %q, want %q (%v)", n, r.Closed, want, err)
		}
	}
	c := Collected{Rows: []Row{{Number: 2, Title: "t2", Closed: "as fixed by 4957ced, no merged PR of its own", Answers: map[string]string{"done": "on a branch"}}}}
	if m := c.matrix(rqs); !strings.Contains(m, "- #2 t2 (closed as fixed by 4957ced, no merged PR of its own): on a branch\n") {
		t.Errorf("the matrix does not head #2's answer with how it closed:\n%s", m)
	}
}

func TestThePreviousRetroIsScored(t *testing.T) {
	t.Parallel()
	c := collect(t, true)
	want := &Score{Retro: 20, Findings: 3, Issues: 2, Closed: 1, Recurred: 1, Items: []ScoreItem{
		// The fixes check broke again, so its class recurred though its issue closed.
		{Title: "PRs without Fixes", Class: "landing", Issue: 21, State: "completed", Recurred: true},
		// Its issue is open: no fix of its landed, so its metric's move is
		// neither credited nor blamed.
		{Title: "Conflicts", Class: "merging", Issue: 22, State: "open", Metric: "conflicts_per_issue", Before: 0.5, Now: 0.5},
		{Title: "Kept as is", Class: "merging", State: "none"},
	}}
	if !reflect.DeepEqual(c.Score, want) {
		t.Fatalf("%+v\nwant %+v", c.Score, want)
	}
	draft, err := c.Draft(rqs)
	if err != nil || !strings.Contains(draft, "| conflicts_per_issue 0.5 → 0.5 (not credited: its issue did not close as completed) |") {
		t.Fatalf("%v\n%s", err, draft)
	}
}

func TestAMetricIsCreditedOnceItsIssueClosedAsCompleted(t *testing.T) {
	t.Parallel()
	a := retroRepo(t, true, "<!-- se:retro attended -->")
	a["repos/o/r/issues/22"] = `{"number":22,"state":"closed","state_reason":"completed"}`
	c, err := Source{Proc: machine, Repo: repo, GitHub: recorded(t, a), Clock: atNow()}.Collect(30)
	if err != nil {
		t.Fatal(err)
	}
	// Its fix landed, and conflicts per issue did not drop: it recurred.
	it := c.Score.Items[1]
	if it.State != "completed" || it.Dropped == nil || *it.Dropped || !it.Recurred || c.Score.Closed != 2 || c.Score.Recurred != 2 {
		t.Fatalf("%+v", c.Score)
	}
}

func TestTheMetricsBlockComparesWithThePreviousRetros(t *testing.T) {
	t.Parallel()
	c := collect(t, true)
	if len(c.History) != 1 || c.History[0].Retro != 20 {
		t.Fatalf("history %+v: #10 posted no report, #20 did", c.History)
	}
	draft, err := c.Draft(rqs)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		"| metric | #20 | now | since the last |",
		"| conflicts_per_issue | 0.5 | 0.5 | same |",
		// The window's sizes move neither way for the better.
		"| closed | 2 | 4 | +2 |",
		"| landed | – | 2 | new |",
		"| ci_reruns_per_issue | 0 | 0.5 | worse (+0.5) |",
		"| takeovers | – | 1 | new |",
		"| duplicates_per_issue | – | 1 | new |",
		"| duplicates | 2 | 1 |",
		"Duplicates: 1 closed as duplicate, 1 issues for a person minted again for an issue one already held back.",
	} {
		if !strings.Contains(draft, want) {
			t.Errorf("the draft lacks %q", want)
		}
	}
	r, _, err := ParseReport(draft)
	if err != nil || !reflect.DeepEqual(r.Metrics, c.Metrics) || r.Previous == nil || r.Previous.Retro != 20 {
		t.Fatalf("the block: %+v %v", r, err)
	}
}

// judged is retro #30's draft with the box's judgment filled in: one
// controversial finding and one for the normal queue.
func judged(t *testing.T, edit func(*RetroReport)) string {
	t.Helper()
	r := RetroReport{
		Retro: 30, Attended: true, Metrics: Metrics{"closed": 4}, Checks: []Broken{},
		Findings: []Lesson{
			{Title: "Refuse a PR without Fixes", Class: "landing", Body: "PR #51 said no Fixes.", Home: "refusal", Check: "fixes"},
			{Title: "Drop the lease on claimed issues", Class: "claims", Body: "It trades speed for safety.", Home: "removal", Controversial: true, Why: "it trades one metric against another"},
		},
		Classes:  []Class{{"landing", "se issue land refuses"}, {"claims", "a person decides"}},
		WentWell: []string{"the landing answers"},
	}
	if edit != nil {
		edit(&r)
	}
	text, err := r.assemble("## The window\nfacts")
	if err != nil {
		t.Fatal(err)
	}
	return text + "\n" + matrixMark + "\n## The matrix\nbig"
}

func TestAReportWithoutJudgmentIsRefused(t *testing.T) {
	t.Parallel()
	for name, edit := range map[string]func(*RetroReport){
		"nothing went well":         func(r *RetroReport) { r.WentWell = nil },
		"an unknown class":          func(r *RetroReport) { r.Findings[0].Class = "nope" },
		"controversial, no why":     func(r *RetroReport) { r.Findings[1].Why = "" },
		"a home that is no fix":     func(r *RetroReport) { r.Findings[0].Home = "hope" },
		"a check that is no check":  func(r *RetroReport) { r.Findings[0].Check = "vibes" },
		"a one-word title":          func(r *RetroReport) { r.Findings[0].Title = "Take" },
		"a title cut off":           func(r *RetroReport) { r.Findings[0].Title = "Count however many takes find it stuck, and" },
		"a title ending in a comma": func(r *RetroReport) { r.Findings[0].Title = "Refuse a PR without Fixes," },
	} {
		if _, err := (Source{Proc: machine, Repo: repo, GitHub: never{t}, Clock: atNow()}).FileReport(30, judged(t, edit)); err == nil || !strings.Contains(err.Error(), "nothing was written") {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestATitleThatSaysNothingIsNamed(t *testing.T) {
	t.Parallel()
	_, err := (Source{Proc: machine, Repo: repo, GitHub: never{t}, Clock: atNow()}).FileReport(30, judged(t, func(r *RetroReport) { r.Findings[1].Title = "Take" }))
	if err == nil || !strings.Contains(err.Error(), `finding 2 ("Take") has a title under five words`) {
		t.Fatal(err)
	}
}

// fileFindings files retro #30's judged report. The repository's last
// number is PR #91, so its issues are #92 on.
func fileFindings(t *testing.T, answers map[string]string) (Filed, *github.Fake) {
	t.Helper()
	gh := recorded(t, answers)
	f, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.FileReport(30, judged(t, nil))
	if err != nil {
		t.Fatal(err)
	}
	return f, gh
}

func TestAnUnattendedRetroCreatesItsIssuesAndCloses(t *testing.T) {
	t.Parallel()
	f, gh := fileFindings(t, retroRepo(t, true, "<!-- se:retro unattended -->"))
	// The normal finding goes into a new misc manifest, #92; the
	// controversial one, for a person, stands at the top.
	if !reflect.DeepEqual(f.Issues, []int{93, 94}) || !reflect.DeepEqual(f.Person, []int{94}) || !f.Ready {
		t.Fatalf("%+v", f)
	}
	if !issueAt(t, gh, 92).labelled(MiscLabel) || issueAt(t, gh, 92).SubIssues.Total != 1 {
		t.Fatalf("%+v", issueAt(t, gh, 92))
	}
	// The normal finding is labelled se alone; the controversial one se-person too.
	normal, controversial := issueAt(t, gh, 93), issueAt(t, gh, 94)
	if len(normal.Labels) != 1 || !normal.labelled(Label) || len(controversial.Labels) != 2 || !controversial.labelled(Label) || !controversial.labelled(PersonLabel) {
		t.Fatalf("%+v\n%+v", normal, controversial)
	}
	if !strings.HasPrefix(normal.Title, "Refuse a PR without Fixes") || !strings.Contains(normal.Body, "Found by the retro #30, class **landing**") || !strings.HasSuffix(normal.Body, NewMark) {
		t.Fatalf("%+v", normal)
	}
	want := []string{
		"POST repos/o/r/issues",
		"POST repos/o/r/issues",
		"POST repos/o/r/issues/92/sub_issues",
		"POST repos/o/r/issues",
		"POST repos/o/r/issues/94/assignees",
		"POST repos/o/r/issues/30/comments",
		"PATCH repos/o/r/issues/30",
		"DELETE repos/o/r/git/refs/heads/issue-30",
	}
	if w := gh.Writes(); !reflect.DeepEqual(w, want) {
		t.Fatalf("%q", w)
	}
	if c := commentsAt(t, gh, 30); len(c) != 1 || !strings.Contains(c[0].Body, "issue: 93") {
		t.Fatalf("the closing report names no issue: %+v", c)
	}
}

func TestAnAttendedRetroClosesToo(t *testing.T) {
	t.Parallel()
	// A person started it, and still nobody waits: the report is its closing
	// comment, and the controversial finding is the issue for the person.
	f, gh := fileFindings(t, retroRepo(t, true, "<!-- se:retro attended -->"))
	if !reflect.DeepEqual(f.Person, []int{94}) {
		t.Fatalf("%+v", f)
	}
	if labelled(t, gh, 30, PersonLabel) {
		t.Fatalf("the retro was given to a person: %q", gh.Writes())
	}
	if issueAt(t, gh, 30).State != "closed" {
		t.Fatalf("the attended retro did not close: %q", gh.Writes())
	}
	c := commentsAt(t, gh, 30)
	report := "body=" + c[len(c)-1].Body
	for _, part := range []string{"body=" + reportMark, "### landing (1)", "**Drop the lease on claimed issues** (removal; for a person: it trades one metric against another)", "- the landing answers", reportBlock} {
		if !strings.Contains(report, part) {
			t.Errorf("the report lacks %q:\n%s", part, report)
		}
	}
	if strings.Contains(report, "The matrix") {
		t.Errorf("the posted report carries the matrix")
	}
}

// A retro posted for the owner before retros stopped waiting is filed as it
// stands, with what the owner moved.
func TestAResumedRetroCreatesTheIssuesAsDecided(t *testing.T) {
	t.Parallel()
	answers := retroRepo(t, true, "<!-- se:retro attended -->")
	answers["repos/o/r/issues/30/comments?per_page=100"] = jsonComments(judged(t, nil), "<!-- se:person -->\nwaits", "move finding 2 to normal", "<!-- se:resume -->\nResumed.")
	f, _ := fileFindings(t, answers)
	if len(f.Issues) != 2 {
		t.Fatalf("%+v", f)
	}
}

func TestARefusedBranchDeletionDoesNotFailTheReport(t *testing.T) {
	t.Parallel()
	answers := retroRepo(t, true, "<!-- se:retro attended -->")
	// Behind a cloud session's proxy, deleting a branch is refused.
	gh := recorded(t, answers)
	gh.Proxy = true
	f, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.FileReport(30, judged(t, nil))
	if err != nil || !strings.HasPrefix(f.Left, "issue-30 stays (") || !strings.Contains(f.Left, "se fleet prune") {
		t.Fatalf("%+v %v", f, err)
	}
}

func TestARuleCheckWhosePRDidNotMergeIsRefused(t *testing.T) {
	t.Parallel()
	a := retroRepo(t, true, "")
	key := "repos/o/r/pulls?state=closed&base=main&per_page=100"
	a[key] = strings.Replace(a[key], `"number":91`, `"number":92`, 1)
	gh := recorded(t, a)
	_, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Collect(30)
	if err == nil || !strings.Contains(err.Error(), "the rule check mark started with PR #91, which is not a merged PR") {
		t.Fatalf("%v", err)
	}
}

func TestByHandCountsAnAnswerThatProposesACommand(t *testing.T) {
	t.Parallel()
	for answer, want := range map[string]bool{
		// #88's answer: nothing scripted, yet it names the command it wants.
		`Nothing scripted. No se command reports "main fails its own check"; se fleet check could run check.sh on origin/main and name that as a finding.`: true,
		"wrote src/scripts/check-claims.sh":    true,
		"merged main by hand twice":            true,
		"none":                                 false,
		"Nothing.":                             false,
		"nothing: se issue land did all of it": false,
		"None. Everything went through the se commands as written": false,
		"": false,
	} {
		if got := byHand(answer); got != want {
			t.Errorf("byHand(%q) = %v, want %v", answer, got, want)
		}
	}
}
