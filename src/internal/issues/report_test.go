// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

func TestAReportIsRefusedWhereItBreaksTheRules(t *testing.T) {
	t.Parallel()
	with := func(change func(r *Report)) Report {
		r := failing("it breaks")
		r.Requirements = append([]Requirement{}, r.Requirements...)
		r.Findings = append([]ReviewFinding{}, r.Findings...)
		change(&r)
		return r
	}
	for _, c := range []struct {
		pass    bool
		rep     Report
		earlier []int
		want    string
	}{
		{true, with(func(r *Report) { r.Findings = nil; r.Requirements[0].Evidence = " " }), nil, `requirement "it holds" has no evidence`},
		{true, with(func(r *Report) { r.Findings = nil; r.Clean = nil }), nil, `no "checked and clean" list`},
		{false, with(func(r *Report) { r.Clean = nil }), nil, `no "checked and clean" list`},
		{true, with(func(r *Report) { r.Findings = nil; r.Commit = "" }), nil, "names no commit"},
		{true, with(func(r *Report) { r.Findings = nil; r.Requirements = nil }), nil, "names no requirement"},
		{true, with(func(*Report) {}), nil, "a pass has no blocking finding"},
		{false, with(func(r *Report) { r.Findings[0].Blocking = false }), nil, "a fail needs a verified blocking finding"},
		{false, with(func(r *Report) { r.Findings[0].Evidence = "" }), nil, `"it breaks" has no evidence`},
		{false, with(func(r *Report) { r.Findings[0].Why = "" }), nil, `"it breaks" has no judgment`},
		{false, with(func(r *Report) { r.Findings[0].Repeats = 3 }), nil, "#3, which is no earlier blocker"},
		// A re-review checks the earlier blockers, every one, and nothing else.
		{false, with(func(*Report) {}), []int{3}, "checks only the earlier blockers (#3)"},
		{false, with(func(r *Report) { r.Requirements[0].Blocker = 4 }), []int{3}, "names #4, which is no earlier blocker"},
		{false, with(func(r *Report) { r.Requirements[0].Blocker = 3 }), []int{3, 5}, "no requirement checks #5"},
		{false, with(func(r *Report) {
			r.Requirements[0].Blocker = 3
			r.Findings = append(r.Findings, ReviewFinding{Title: "nit", Evidence: "y.go:1", Why: "style"})
		}), []int{3}, `raises no new non-blocking finding, and "nit" is one`},
	} {
		if err := c.rep.check(c.pass, c.earlier); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%+v: %v, want %q", c, err, c.want)
		}
	}
	// A fail may leave a requirement without evidence; a re-review that
	// checks its blockers passes.
	if err := with(func(r *Report) { r.Requirements[0].Evidence = "" }).check(false, nil); err != nil {
		t.Error(err)
	}
	if err := with(func(r *Report) { r.Findings = nil; r.Requirements[0].Blocker = 3 }).check(true, []int{3}); err != nil {
		t.Error(err)
	}
}

// reviewWorld is a gate #1, ready for review, whose leaf #2 was worked by
// someone else; the repository's last issue is #9, so issues created are
// numbered from 10 up.
func reviewWorld(t *testing.T) (Source, *github.Fake) {
	gh := recorded(t, map[string]string{
		listPath:             list(node(1, 1, ReviewLabel)),
		refsPath:             `[]`,
		subsPath(1):          subs(-2),
		commentsPath(2):      workedBy(Worker{Session: "w", Workspace: "/w"}),
		"repos/o/r/issues/9": `{"number":9,"state":"closed"}`,
	})
	return Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}, gh
}

func TestFindingsBecomeFinalIssuesBlockingOnesUnderTheGate(t *testing.T) {
	t.Parallel()
	s, gh := reviewWorld(t)
	rep := failing("it breaks")
	for k := 1; k <= 7; k++ {
		rep.Findings = append(rep.Findings, ReviewFinding{Title: fmt.Sprintf("nit %d", k), Evidence: "y.go:1", Why: "fixable"})
	}
	r, err := s.Review(1, Worker{Session: "r", Workspace: "/r"}, false, rep)
	if err != nil {
		t.Fatal(err)
	}
	// The non-blocking ones go into a new misc manifest, #11.
	if !reflect.DeepEqual(numbers(r.Fixes), []int{10}) || !reflect.DeepEqual(numbers(r.Filed), []int{12, 13, 14, 15, 16}) || r.Unfiled != 2 || r.Passed || r.Closed || len(r.Accepted) != 0 {
		t.Fatalf("%+v", r)
	}
	for _, n := range []int{10, 12, 13, 14, 15, 16} {
		if i := issueAt(t, gh, n); !i.labelled(Label) || !i.labelled(FinalLabel) {
			t.Errorf("#%d is not se-final: %+v", n, i)
		}
	}
	if !reflect.DeepEqual(linksOf(t, gh, subsPath(11)), []int{12, 13, 14, 15, 16}) {
		t.Fatalf("the misc manifest holds %v", linksOf(t, gh, subsPath(11)))
	}
	if created := gh.Writes(); len(created) != 14 || issueAt(t, gh, 10).Title != "it breaks" || !reflect.DeepEqual(linksOf(t, gh, subsPath(1)), []int{2, 10}) {
		t.Fatalf("created %q, under the gate %v", created, linksOf(t, gh, subsPath(1)))
	}
	report := commentsAt(t, gh, 1)[0].Body
	for _, want := range []string{
		"- **it breaks** (blocking, #10)", "- **nit 1** (not blocking, #12)", "- **nit 7** (not blocking, not filed (past the first 5))",
		"2 more non-blocking finding(s) counted, not filed.", "### Checked and clean\n- the tests: none weakened",
	} {
		if !strings.Contains(report, want) {
			t.Errorf("the report lacks %q:\n%s", want, report)
		}
	}
	// Its block is read back: the next review of #1 is a re-review of #10.
	v := verdictMark.FindStringSubmatch(report)
	if v == nil {
		t.Fatal(report)
	}
	got, err := s.lastVerdict(1)
	if err != nil || !reflect.DeepEqual(got.blockers(), []int{10}) {
		t.Fatalf("%+v %v", got, err)
	}
}

func TestAReReviewIsLimitedToTheEarlierBlockers(t *testing.T) {
	t.Parallel()
	s, gh := reviewWorld(t)
	// #1's last review failed on #3, which has landed since.
	earlier := Verdict{Report: failing("three")}
	earlier.Report.Findings[0].Issue = 3
	seed(t, gh, map[string]string{
		subsPath(1):     subs(-2, -3),
		commentsPath(3): workedBy(Worker{Session: "f", Workspace: "/f"}),
		commentsPath(1): fmt.Sprintf(`[{"body":%q}]`, earlier.render(Worker{Session: "r0", Workspace: "/r0"}, MaxFiled)),
	})
	r := Worker{Session: "r", Workspace: "/r"}
	if _, err := s.Review(1, r, true, passing); err == nil || !strings.Contains(err.Error(), "checks only the earlier blockers (#3)") {
		t.Fatalf("%v", err)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused review wrote %q", w)
	}
	// The re-review finds #3's problem again: #3 was final, so the repeat
	// is accepted, files nothing, and with nothing else blocking #1 closes.
	again := failing("three, again")
	again.Requirements = []Requirement{{Item: "three is fixed", Evidence: "x.go:3 still breaks", Blocker: 3}}
	again.Findings[0].Repeats = 3
	got, err := s.Review(1, r, false, again)
	if err != nil || !got.Closed || got.Passed || !reflect.DeepEqual(got.Accepted, []int{3}) || len(got.Fixes)+len(got.Filed) != 0 {
		t.Fatalf("%+v %v", got, err)
	}
	if w := gh.Writes(); len(w) < 2 || w[0] != "POST repos/o/r/issues/1/comments" || w[1] != "PATCH repos/o/r/issues/1" {
		t.Fatalf("%q", w)
	}
	for _, w := range gh.Writes() {
		if w == "POST repos/o/r/issues" || strings.Contains(w, "blocked_by") || strings.Contains(w, "labels") {
			t.Fatalf("the re-review minted or held something: %q", gh.Writes())
		}
	}
	c := commentsAt(t, gh, 1)
	if len(c) != 2 || !strings.HasPrefix(c[1].Body, "## Re-review: FAIL") || !strings.Contains(c[1].Body, "repeats #3: an accepted repeat, it blocks no more") ||
		!strings.Contains(c[1].Body, "the reviewer accepts the repeats, and the gate closes") {
		t.Fatalf("%+v", c)
	}
	// An accepted repeat blocks no more: it is no blocker of a next review.
	if v, err := s.lastVerdict(1); err != nil || len(v.blockers()) != 0 {
		t.Fatalf("%+v %v", v, err)
	}
}
