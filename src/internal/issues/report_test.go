// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
)

func TestAReportIsRefusedWhereItBreaksTheRules(t *testing.T) {
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
// someone else; issues created come back numbered from 10 up.
func reviewWorld(t *testing.T) (Source, map[string]string, *[][]string) {
	answers := map[string]string{
		listPath:                        list(node(1, 1, ReviewLabel)),
		refsPath:                        `[]`,
		subsPath(1):                     subs(-2),
		commentsPath(2):                 workedBy(Worker{Session: "w", Workspace: "/w"}),
		"repos/o/r/issues/1":            `{"id":1001,"number":1}`,
		"repos/o/r/issues/1/comments":   `{}`,
		"repos/o/r/issues/1/labels":     `{}`,
		"repos/o/r/issues/1/assignees":  `{}`,
		"repos/o/r/issues/1/sub_issues": `{}`,
	}
	gh, wrote := reviewGH(t, answers)
	next := 10
	s := Source{Repo: repo, GH: func(args ...string) ([]byte, error) {
		if args[len(args)-1] == "repos/o/r/issues" {
			next++
			answers["repos/o/r/issues"] = fmt.Sprintf(`{"id":%d,"number":%d,"title":"f%d","html_url":"u%d"}`, 1000+next-1, next-1, next-1, next-1)
		}
		return gh(args...)
	}}
	return s, answers, wrote
}

func TestFindingsBecomeFinalIssuesBlockingOnesUnderTheGate(t *testing.T) {
	s, _, wrote := reviewWorld(t)
	rep := failing("it breaks")
	for k := 1; k <= 7; k++ {
		rep.Findings = append(rep.Findings, ReviewFinding{Title: fmt.Sprintf("nit %d", k), Evidence: "y.go:1", Why: "fixable"})
	}
	r, err := s.Review(1, Worker{Session: "r", Workspace: "/r"}, false, rep)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(numbers(r.Fixes), []int{10}) || !reflect.DeepEqual(numbers(r.Filed), []int{11, 12, 13, 14, 15}) || r.Unfiled != 2 || r.Passed || r.Person {
		t.Fatalf("%+v", r)
	}
	var created, under []string
	var report string
	for _, w := range *wrote {
		switch path := w[len(w)-1]; path {
		case "repos/o/r/issues":
			if !reflect.DeepEqual(w[len(w)-5:], []string{"-f", "labels[]=se", "-f", "labels[]=se-final", path}) {
				t.Errorf("not se-final: %q", w)
			}
			created = append(created, w[4])
		case "repos/o/r/issues/1/sub_issues":
			under = append(under, w[4])
		case "repos/o/r/issues/1/comments":
			report = w[4]
		}
	}
	if len(created) != 6 || created[0] != "title=it breaks" || !reflect.DeepEqual(under, []string{"sub_issue_id=1010"}) {
		t.Fatalf("created %q, under the gate %q", created, under)
	}
	for _, want := range []string{
		"- **it breaks** (blocking, #10)", "- **nit 1** (not blocking, #11)", "- **nit 7** (not blocking, not filed (past the first five))",
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
	s.GH = recorded(t, map[string]string{commentsPath(1): fmt.Sprintf(`[{"body":%q}]`, report)})
	got, err := s.lastVerdict(1)
	if err != nil || !reflect.DeepEqual(got.blockers(), []int{10}) {
		t.Fatalf("%+v %v", got, err)
	}
}

func TestAReReviewIsLimitedToTheEarlierBlockers(t *testing.T) {
	s, answers, wrote := reviewWorld(t)
	// #1's last review failed on #3, which has landed since.
	earlier := Verdict{Report: failing("three")}
	earlier.Report.Findings[0].Issue = 3
	answers[subsPath(1)] = subs(-2, -3)
	answers[commentsPath(3)] = workedBy(Worker{Session: "f", Workspace: "/f"})
	answers[commentsPath(1)] = fmt.Sprintf(`[{"body":%q}]`, earlier.render(Worker{Session: "r0", Workspace: "/r0"}))
	answers[listPath] = list(node(1, 2, ReviewLabel))
	r := Worker{Session: "r", Workspace: "/r"}
	if _, err := s.Review(1, r, true, passing); err == nil || !strings.Contains(err.Error(), "checks only the earlier blockers (#3)") {
		t.Fatalf("%v", err)
	}
	if len(*wrote) != 0 {
		t.Fatalf("a refused review wrote %q", *wrote)
	}
	// The re-review finds #3's problem again: #3 was final, so #1 goes to a person.
	again := failing("three, again")
	again.Requirements = []Requirement{{Item: "three is fixed", Evidence: "x.go:3 still breaks", Blocker: 3}}
	again.Findings[0].Repeats = 3
	got, err := s.Review(1, r, false, again)
	if err != nil || !got.Person || len(got.Fixes)+len(got.Filed) != 0 {
		t.Fatalf("%+v %v", got, err)
	}
	var paths []string
	for _, w := range *wrote {
		paths = append(paths, w[len(w)-2]+" "+w[len(w)-1])
	}
	if len(paths) != 4 || !strings.HasPrefix(paths[0], "body=## Re-review: FAIL") || !strings.Contains(paths[0], "repeats #3, so this goes to a person") ||
		paths[1] != "labels[]=se-person repos/o/r/issues/1/labels" || paths[2] != "assignees[]=o repos/o/r/issues/1/assignees" ||
		!strings.Contains(paths[3], "Its re-review finds the problem of #3 (three, again) again") {
		t.Fatalf("%q", paths)
	}
}
