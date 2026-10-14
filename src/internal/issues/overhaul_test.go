// Internal test package: it reuses the recorded answers of the retro and cadence tests.
package issues

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
)

// overhaulRepo records o/r as cadenceRepo(10, 0) does, a retro due, with
// overhaul #15 closed on September 15th and n retros closed after it;
// openOverhaul, where it is not 0, is an open overhaul.
func overhaulRepo(n, openOverhaul int) map[string]string {
	a := cadenceRepo(10, 0)
	var retros []string
	for k := 0; k < n; k++ {
		retros = append(retros, fmt.Sprintf(`{"number":%d,"state":"closed","closed_at":"2026-09-2%dT00:00:00Z","labels":[{"name":"se-retro"}]}`, 200+k, k))
	}
	// Before the window, touched inside it: the list holds it, the count does not.
	retros = append(retros, `{"number":9,"state":"closed","closed_at":"2026-09-01T00:00:00Z"}`)
	open := `[]`
	if openOverhaul != 0 {
		open = fmt.Sprintf(`[{"number":%d,"state":"open"}]`, openOverhaul)
	}
	a["repos/o/r/issues?labels=se-overhaul&state=closed&per_page=100"] = `[{"number":15,"state":"closed","closed_at":"2026-09-15T00:00:00Z"}]`
	a["repos/o/r/issues?labels=se-overhaul&state=open&per_page=100"] = open
	a["repos/o/r/issues?labels=se-retro&state=closed&per_page=100&since=2026-09-15T00:00:00Z"] = "[" + strings.Join(retros, ",") + "]"
	return a
}

func TestFourRetrosStartNoOverhaulAndTheDueRetroIsTaken(t *testing.T) {
	_, a, _ := boxes(t)
	gh, w := writing(t, overhaulRepo(4, 0))
	took, ok, c, err := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}.TakeDue(a)
	if err != nil || !ok || !took.Retro || took.Overhaul || c.Kind != "retro" || len(*w) != 1 || !strings.Contains(strings.Join((*w)[0], " "), "labels[]=se-retro") {
		t.Fatalf("took %+v %v, %+v %v, writes %q", took, ok, c, err, *w)
	}
	o, err := Source{Proc: machine, Repo: repo, GH: recorded(t, overhaulRepo(4, 0)), Clock: atNow()}.OverhaulCadence()
	if err != nil || o.Closed != 4 || o.Due() || o.Line() != "4 retros closed since the overhaul #15 closed; an overhaul is due at 5." {
		t.Fatalf("%+v %v %q", o, err, o.Line())
	}
}

func TestFiveRetrosStartAnUnattendedOverhaulAndTakeItFirst(t *testing.T) {
	_, a, _ := boxes(t)
	gh, w := writing(t, overhaulRepo(5, 0))
	took, ok, c, err := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}.TakeDue(a)
	if err != nil || !ok || !took.Overhaul || took.Retro || c.Kind != "overhaul" || c.Closed != 5 || c.Every != OverhaulCadence {
		t.Fatalf("took %+v %v, %+v %v", took, ok, c, err)
	}
	made := strings.Join((*w)[0], " ")
	if len(*w) != 1 || !strings.Contains(made, overhaulUnattendedMark) || !strings.Contains(made, "labels[]=se-overhaul") || !strings.Contains(made, "title=SE overhaul 2026-10-13") || !strings.Contains(made, "The last overhaul was #15") {
		t.Fatalf("writes %q", *w)
	}
	if got := run(t, a, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-30" {
		t.Fatalf("a is on %s", got)
	}
}

func TestAnOpenOverhaulBlocksASecond(t *testing.T) {
	c, err := Source{Proc: machine, Repo: repo, GH: recorded(t, overhaulRepo(7, 31)), Clock: atNow()}.OverhaulCadence()
	if err != nil || c.Open != 31 || c.Due() || !strings.HasSuffix(c.Line(), "; the overhaul #31 is open.") {
		t.Fatalf("%+v %v %q", c, err, c.Line())
	}
}

func TestThePrinciplesAreReadFromTheSpec(t *testing.T) {
	ps, err := Principles("../../..")
	if err != nil || len(ps) < 16 {
		t.Fatalf("%d principles, %v", len(ps), err)
	}
	if p := ps[0]; p.Number != 1 || p.Name != "Mechanize first" || !p.Mechanical || !strings.HasPrefix(p.CheckedBy, "retro, mechanically") {
		t.Fatalf("%+v", p)
	}
	if p := ps[3]; p.Name != "Modularity" || p.Mechanical {
		t.Fatalf("%+v", p)
	}
}

// retroWithClasses is retro n's report with one finding, and its issue, per class;
// prevRecurred is how many of the retro before it it found recurred.
func retroWithClasses(t *testing.T, n int, prevRecurred int, classes ...string) string {
	t.Helper()
	r := RetroReport{Retro: n, Metrics: Metrics{"closed": float64(n)}, Checks: []Broken{{Kind: "fixes"}}, WentWell: []string{"w"}}
	if prevRecurred > 0 {
		r.Previous = &Score{Recurred: prevRecurred}
	}
	for k, c := range classes {
		r.Classes = append(r.Classes, Class{c, "fix"})
		r.Findings = append(r.Findings, Lesson{Title: c, Class: c, Body: "b", Home: "check", Issue: 300 + n + k})
	}
	text, err := r.assemble("facts")
	if err != nil {
		t.Fatal(err)
	}
	return text
}

func TestCollectReadsTheLatestRetrosAndThePreviousOverhaul(t *testing.T) {
	prev, err := OverhaulReport{Overhaul: 15, Findings: []Straying{{Title: "Split the engine", Principle: 4, Issue: 16}}}.assemble("old")
	if err != nil {
		t.Fatal(err)
	}
	gh := recorded(t, map[string]string{
		"repos/o/r/issues/31": `{"number":31,"state":"open","body":"<!-- se:overhaul attended -->","labels":[{"name":"se-overhaul"}]}`,
		// Six retros closed, one without a report; the overhaul reads the last five reports.
		"repos/o/r/issues?labels=se-retro&state=closed&per_page=100": `[` +
			`{"number":20,"state":"closed","closed_at":"2026-09-02T00:00:00Z"},{"number":21,"state":"closed","closed_at":"2026-09-03T00:00:00Z"},` +
			`{"number":22,"state":"closed","closed_at":"2026-09-04T00:00:00Z"},{"number":23,"state":"closed","closed_at":"2026-09-05T00:00:00Z"},` +
			`{"number":24,"state":"closed","closed_at":"2026-09-06T00:00:00Z"},{"number":25,"state":"closed","closed_at":"2026-09-07T00:00:00Z"},` +
			`{"number":26,"state":"closed","closed_at":"2026-09-08T00:00:00Z"}]`,
		"repos/o/r/issues/26/comments?per_page=100":                     `[]`,
		"repos/o/r/issues/25/comments?per_page=100":                     jsonComments(retroWithClasses(t, 25, 1, "merging")),
		"repos/o/r/issues/24/comments?per_page=100":                     jsonComments(retroWithClasses(t, 24, 0, "merging", "landing")),
		"repos/o/r/issues/23/comments?per_page=100":                     jsonComments(retroWithClasses(t, 23, 0)),
		"repos/o/r/issues/22/comments?per_page=100":                     jsonComments(retroWithClasses(t, 22, 0, "landing")),
		"repos/o/r/issues/21/comments?per_page=100":                     jsonComments(retroWithClasses(t, 21, 0)),
		"repos/o/r/issues/325":                                          `{"number":325,"state":"open"}`,
		"repos/o/r/issues/324":                                          `{"number":324,"state":"closed","state_reason":"completed"}`,
		"repos/o/r/issues/322":                                          `{"number":322,"state":"closed","state_reason":"not_planned"}`,
		"repos/o/r/issues?labels=se-overhaul&state=closed&per_page=100": `[{"number":15,"state":"closed","closed_at":"2026-09-01T00:00:00Z"}]`,
		"repos/o/r/issues/15/comments?per_page=100":                     jsonComments(prev),
		"repos/o/r/issues/16":                                           `{"number":16,"state":"closed","state_reason":"completed"}`,
	})
	r, err := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}.CollectOverhaul(31, []Principle{{Number: 1, Name: "Mechanize first"}})
	if err != nil {
		t.Fatal(err)
	}
	var got []int
	for _, run := range r.Retros {
		got = append(got, run.Retro)
	}
	if !reflect.DeepEqual(got, []int{21, 22, 23, 24, 25}) || !r.Attended || r.Previous != 15 {
		t.Fatalf("%v %+v", got, r)
	}
	// #24's findings: #324 closed, #325 open; #25 scored #24's as recurred once.
	if run := r.Retros[3]; run.Issues != 2 || run.Closed != 1 || run.Recurred != 1 || run.Broken["fixes"] != 1 {
		t.Fatalf("%+v", run)
	}
	if !reflect.DeepEqual(r.Recurring, []string{"landing", "merging"}) || !reflect.DeepEqual(r.Earlier, []Overhauled{{Title: "Split the engine", Principle: 4, Issue: 16, State: "completed"}}) {
		t.Fatalf("%v %+v", r.Recurring, r.Earlier)
	}
	draft, err := r.OverhaulDraft()
	if err != nil {
		t.Fatal(err)
	}
	for _, part := range []string{"| 1 | Mechanize first |", "| broken `fixes` | 1 | 1 | 1 | 1 | 1 |", "| #24 | 2 | 2 | 1 | 1 |", "Classes more than one of them named: landing, merging.", "| Split the engine | 4 | #16 | completed |", "`se overhaul file` writes this part"} {
		if !strings.Contains(draft, part) {
			t.Errorf("the draft lacks %q:\n%s", part, draft)
		}
	}
	back, _, err := ParseOverhaul(draft)
	if err != nil || !reflect.DeepEqual(back.Retros, r.Retros) || back.Overhaul != 31 {
		t.Fatalf("the block: %+v %v", back, err)
	}
}

// overhauled is overhaul #30's draft with the box's judgment: a finding for
// the normal queue, a principle change it left uncontroversial, and an
// outside idea for a person.
func overhauled(t *testing.T, edit func(*OverhaulReport)) string {
	t.Helper()
	r := OverhaulReport{
		Overhaul:   30,
		Principles: []Principle{{Number: 1, Name: "Mechanize first"}, {Number: 2, Name: "Single point of truth"}},
		Verdicts:   []Judged{{1, "slightly", "the landing answers are typed by hand"}, {2, "none", "held"}},
		LookedAt:   LookedAt{"agent tools converge on hooks", "the README is current", "none missing", "the metrics fell", "the survey runs one call at a time", "nothing by hand", "nothing to drop"},
		Findings: []Straying{
			{Title: "Prefill the landing answers", Body: "by-hand answers repeat.", Area: "principle", Principle: 1, Place: "spec/landing.yaml", Strays: "slightly"},
			{Title: "Add a principle on cost", Body: "Nothing weighs tokens.", Area: "principles", Place: "spec/principles.md", Strays: "far"},
			{Title: "Contract tests for gh", Body: "Others record real answers.", Area: "outside", Principle: 2, Place: "src/internal/issues", Strays: "slightly", Sources: []string{"https://example.com/pact"}, Controversial: true, Why: "the box is not sure"},
		},
		WentWell: []string{"the cadence"},
	}
	if edit != nil {
		edit(&r)
	}
	text, err := r.assemble("## The principles\nfacts")
	if err != nil {
		t.Fatal(err)
	}
	return text
}

func overhaulAnswers(body string) map[string]string {
	return map[string]string{
		"repos/o/r/issues/30":                       fmt.Sprintf(`{"number":30,"title":"SE overhaul","state":"open","html_url":"u30","body":%q,"labels":[{"name":"se"},{"name":"se-overhaul"}]}`, body),
		"repos/o/r/issues/30/comments?per_page=100": `[]`,
		"repos/o/r/issues/30/comments":              `{"id":1}`,
		"repos/o/r/issues/30/labels":                `[]`,
		"repos/o/r/issues/30/assignees":             `{}`,
		"repos/o/r/issues":                          `{"number":40,"id":4000,"html_url":"u40"}`,
		"repos/o/r/issues/40/assignees":             `{}`,
	}
}

func TestAnOverhaulMintsByTheControversialRuleAndCloses(t *testing.T) {
	gh, calls := writes(t, overhaulAnswers(overhaulUnattendedMark))
	f, err := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}.FileOverhaul(30, overhauled(t, nil))
	if err != nil || len(f.Issues) != 3 || len(f.Person) != 2 {
		t.Fatalf("%+v %v", f, err)
	}
	var created, writes []string
	var report string
	for _, c := range *calls {
		if c[len(c)-1] == "repos/o/r/issues" {
			created = append(created, strings.Join(c, " "))
		}
		if c[1] == "-X" {
			writes = append(writes, c[2]+" "+c[len(c)-1])
		}
		if c[len(c)-1] == "repos/o/r/issues/30/comments" {
			report = c[4]
		}
	}
	// The normal finding is labelled se alone; the principle change, made
	// controversial, and the unsure one se-person too.
	if strings.Contains(created[0], PersonLabel) || !strings.Contains(created[0], "it strays slightly from principle 1, at spec/landing.yaml") ||
		!strings.Contains(created[1], "labels[]="+PersonLabel) || !strings.Contains(created[1], "waits for a person: it changes a design principle") ||
		!strings.Contains(created[2], "labels[]="+PersonLabel) || !strings.Contains(created[2], "Sources: https://example.com/pact") {
		t.Fatalf("%q", created)
	}
	want := []string{
		"POST repos/o/r/issues", "POST repos/o/r/issues", "POST repos/o/r/issues/40/assignees",
		"POST repos/o/r/issues", "POST repos/o/r/issues/40/assignees",
		"POST repos/o/r/issues/30/comments", "PATCH repos/o/r/issues/30", "DELETE repos/o/r/git/refs/heads/issue-30",
	}
	if !reflect.DeepEqual(writes, want) {
		t.Fatalf("%q", writes)
	}
	// The closing comment is the report, its block naming the issues, for the next overhaul.
	back, _, err := ParseOverhaul(strings.TrimPrefix(report, "body="))
	if err != nil || back.Findings[0].Issue != 40 || !back.Findings[1].Controversial || back.Verdicts[0].Strays != "slightly" {
		t.Fatalf("%+v %v", back, err)
	}
	for _, part := range []string{"| 1 | Mechanize first | slightly |", "**Add a principle on cost** (principles, principle 0, strays far, at spec/principles.md; for a person: it changes a design principle): #40", "- **The outside world:** agent tools converge on hooks", "**Speed (what could run in parallel, or ask the server for more at once):** the survey runs one call at a time"} {
		if !strings.Contains(report, part) {
			t.Errorf("the report lacks %q:\n%s", part, report)
		}
	}
}

func TestAnAttendedOverhaulClosesToo(t *testing.T) {
	// A person started it, and still nobody waits: its controversial
	// findings are the issues for the person.
	gh, calls := writes(t, overhaulAnswers("<!-- se:overhaul attended -->"))
	f, err := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}.FileOverhaul(30, overhauled(t, nil))
	if err != nil || len(f.Issues) != 3 || len(f.Person) != 2 {
		t.Fatalf("%+v %v", f, err)
	}
	closed := false
	for _, c := range *calls {
		if c[len(c)-1] == "repos/o/r/issues/30/labels" {
			t.Fatalf("the overhaul was given to a person: %q", c)
		}
		closed = closed || c[len(c)-1] == "repos/o/r/issues/30" && c[1] == "-X"
	}
	if !closed {
		t.Fatalf("the attended overhaul did not close: %q", *calls)
	}
}

func TestAnOverhaulWithoutJudgmentIsRefused(t *testing.T) {
	never := func(args ...string) ([]byte, error) {
		t.Fatalf("gh %v for a refused overhaul", args)
		return nil, nil
	}
	for name, edit := range map[string]func(*OverhaulReport){
		"a principle without verdict": func(r *OverhaulReport) { r.Verdicts = r.Verdicts[:1] },
		"an outside idea, no source":  func(r *OverhaulReport) { r.Findings[2].Sources = nil },
		"nothing on consistency":      func(r *OverhaulReport) { r.LookedAt.Consistency = "" },
		"nothing on speed":            func(r *OverhaulReport) { r.LookedAt.Speed = "" },
		"a finding without a place":   func(r *OverhaulReport) { r.Findings[0].Place = "" },
		"a principle that is no one":  func(r *OverhaulReport) { r.Findings[0].Principle = 9 },
		"strays none":                 func(r *OverhaulReport) { r.Findings[0].Strays = "none" },
		"nothing went well":           func(r *OverhaulReport) { r.WentWell = nil },
	} {
		if _, err := (Source{Proc: machine, Repo: repo, GH: never, Clock: atNow()}).FileOverhaul(30, overhauled(t, edit)); err == nil || !strings.Contains(err.Error(), "nothing was written") {
			t.Errorf("%s: %v", name, err)
		}
	}
}
