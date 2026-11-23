package template

import (
	"context"
	"strings"
	"testing"

	"kern/index"
)

// Each of the five adapters SE#1683 left to Python is judged in Go: the verb check passes the text
// its writer writes and refuses a broken one with its checker's own refusal; the shared cases hold
// every answer to the Python engine's.
func TestTheVerbCheckJudgesEachOfTheFiveAdapters(t *testing.T) {
	startComponent(t)
	block := "```yaml\n%s\n```\n"
	review := `{"pull": 7, "verdict": "pass", "head": "0123456789abcdef0123456789abcdef01234567", "landed": true, "acceptance": [{"item": "It works.", "evidence": "tests pass"}], "findings": [], "clean": ["the code"]}`
	retro := `{"findings": [], "classes": [], "went_well": ["the cases"]}`
	overhaul := `{"rules": [{"id": "gen-001"}], "verdicts": [{"rule": "gen-001", "strays": "none", "how": "kept"}], "looked_at": {"outside": "x", "consistency": "x", "rules": "x", "retro": "x", "speed": "x", "mechanize": "x", "removal": "x"}, "findings": [], "went_well": ["the cases"]}`
	subject := "Integrate plain-issue-titles"
	cases := []struct {
		template, passes, refused, refusal string
		title                              *string
	}{
		{"field-report", fieldReport("**Result:** complete"), fieldReport("**Result:** done"), "Result must be exactly complete or partial", nil},
		{"merge-message", "A body.\n\nRelease-kind: minor\n", "A body.\n", "it states no kind", &subject},
		{"review", "<!-- se:review -->\n" + sprintf(block, review), "<!-- se:review -->\n" + sprintf(block, strings.Replace(review, `"pass"`, `"decline"`, 1)), "A decline needs the evidence", nil},
		{"retro", "<!-- se:retro-yaml -->\n" + sprintf(block, retro), "<!-- se:retro-yaml -->\n" + sprintf(block, `{"findings": [], "classes": [], "went_well": []}`), "`went_well` is empty", nil},
		{"overhaul", "<!-- se:overhaul-yaml -->\n" + sprintf(block, overhaul), "<!-- se:overhaul-yaml -->\n" + sprintf(block, strings.Replace(overhaul, `"none"`, `"wide"`, 1)), "strays is one of none, slightly, far", nil},
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

// An adapter written wrong for the text fails the check, naming the checker, as the Python
// engine's TemplateError does; it never passes.
func TestAnAdapterWrittenWrongFailsTheCheck(t *testing.T) {
	startComponent(t)
	_, err := Component.Serve(context.Background(), "check", map[string]any{"template": "retro", "body": "<!-- se:retro-yaml -->\n```yaml\n[]\n```\n"})
	if err == nil || !strings.Contains(err.Error(), "templates/retro.md: retro:judgment_problems failed (AttributeError: 'list' object has no attribute 'get'); fix its adapter") {
		t.Fatalf("a list as the retro's block did not fail the check: %v", err)
	}
}

func sprintf(format, value string) string { return strings.Replace(format, "%s", value, 1) }

func fieldReport(result string) string {
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

**Suite time:** None

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

- **Went well:** x
- **Cost time:** y
- **Proposed improvement:** z
<!-- se:field-report:end -->
`
}
