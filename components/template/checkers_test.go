package template

import (
	"context"
	"strings"
	"testing"

	"kern/index"
)

// Each of SE's adapters SE#1683 left to Python is judged in Go (the retro and the overhaul are
// fielded templates since SE#1678): the verb check passes the text
// its writer writes and refuses a broken one with its checker's own refusal; the shared cases hold
// every answer to the Python engine's.
func TestTheVerbCheckJudgesEachOfSEsAdapters(t *testing.T) {
	startComponent(t)
	block := "```yaml\n%s\n```\n"
	review := `{"pull": 7, "verdict": "pass", "head": "0123456789abcdef0123456789abcdef01234567", "landed": true, "acceptance": [{"item": "It works.", "evidence": "tests pass"}], "findings": [], "clean": ["the code"]}`
	subject := "Integrate plain-issue-titles"
	cases := []struct {
		template, passes, refused, refusal string
		title                              *string
	}{
		{"field-report", fieldReport(t, "**Result:** complete"), fieldReport(t, "**Result:** done"), "Result must be exactly complete or partial", nil},
		{"merge-message", "A body.\n\nRelease-kind: minor\n", "A body.\n", "it states no kind", &subject},
		{"review", "<!-- se:review -->\n" + sprintf(block, review), "<!-- se:review -->\n" + sprintf(block, strings.Replace(review, `"pass"`, `"decline"`, 1)), "A decline needs the evidence", nil},
	}
	for _, c := range cases {
		for _, body := range []string{c.passes, c.refused} {
			request := map[string]any{"template": c.template, "body": body}
			if c.title != nil {
				request["title"] = *c.title
			}
			answer, err := Component.Serve(context.Background(), "check", request)
			if err != nil {
				t.Fatalf("%s: check failed: %v", c.template, err)
			}
			var checked Checked
			if err := index.Recode(answer, &checked); err != nil {
				t.Fatal(err)
			}
			if body == c.passes && checked.Refused {
				t.Errorf("%s: the text its writer writes is refused: %+v", c.template, checked.Findings)
			}
			if body == c.refused && (!checked.Refused || !strings.Contains(asJSON(checked.Findings), c.refusal)) {
				t.Errorf("%s: a broken text is not refused for %q: %+v", c.template, c.refusal, checked.Findings)
			}
		}
	}
}

// An adapter written wrong for its checker fails the check, naming the checker, as the Python
// engine's TemplateError does; it never passes.
func TestAnAdapterWrittenWrongFailsTheCheck(t *testing.T) {
	note := "---\nname: report\nversion: 1.0.0\nkind: document\ntags: [\"test\"]\nreader: fleet\nsays: A report.\nchecker: work_tickets:field_report_problems\napplies:\n  actions: [\"comment.create\"]\nadapter:\n  with:\n    issue_body: \"x\"\n---\n"
	catalog, err := loadFixture(map[string]string{"report.md": note})
	if err != nil {
		t.Fatal(err)
	}
	report := catalog["report"]
	_, err = CheckText(report, Parse(report, "Text.\n", nil), nil)
	if err == nil || !strings.Contains(err.Error(), "templates/report.md: work_tickets:field_report_problems failed (NotImplementedError") {
		t.Fatalf("an adapter that hands the field report's checker an issue body did not fail the check: %v", err)
	}
}

func sprintf(format, value string) string { return strings.Replace(format, "%s", value, 1) }

func fieldReport(t *testing.T, result string) string {
	return "<!-- se:field-report -->\n**Work issue:** #12  **Branch:** `b`  " + result + `
**Tested against ` + "`main`" + `:** ` + "`0123456`" + `
**Branch tip:** ` + "`abcdef1`" + `
**Release kind:** patch — a fix
**Re-integration kind:** patch

## User requirement (quoted back)

> It.

## Delivered

| Work issue item | Result | Commits | Evidence |
|---|---|---|---|
| 1 | done | a | b |

**Commit groupings:** None

## Not delivered

None

## Removed behaviour, deleted or weakened tests, and authored prose

None

## Review responses

None

## Decisions

None

## Spec gaps

None

## Tickets for other repositories

None

## Retro

` + questions(t) + `
<!-- se:field-report:end -->
`
}

// questions is the standing questions answered "None.", one "###" section each.
func questions(t *testing.T) string {
	t.Helper()
	block, err := standingQuestions()
	if err != nil {
		t.Fatal(err)
	}
	var b strings.Builder
	for _, item := range block.Fields {
		b.WriteString("### " + item.Heading + "\n\nNone.\n\n")
	}
	return b.String()
}
