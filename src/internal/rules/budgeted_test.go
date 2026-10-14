package rules_test

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/rules"
)

const budgetsYAML = `total: {ms: 1000, hard: false}
classes:
  instant: {ms: 1000, hard: false}
commands:
  help: instant
  gone: instant
  status: slow
hooks:
  session.start: instant
`

const hooksTSX = `on('session.start', async ($, e, next) => {
  took($, 'session.start', began)
})
on('*', async ($, e, next) => {
  took($, '*', began)
})
`

func TestEveryCommandAndHookHasABudgetClass(t *testing.T) {
	t.Parallel()
	repo := &rules.Repo{Commands: map[string][]string{"help": nil, "status": nil, "issue land": nil}}
	found := checkIn(t, repo, "budgeted", map[string]string{
		"spec/budgets.yaml":             budgetsYAML,
		"src/plugin/hooks/register.tsx": hooksTSX,
	})
	want := []string{
		`spec/budgets.yaml:7: budgeted: status names the class "slow", which classes does not hold`,
		`spec/budgets.yaml:4: budgeted: the se command "issue land" has no class under commands`,
		`spec/budgets.yaml:6: budgeted: "gone" is no se command`,
		`src/plugin/hooks/register.tsx:5: budgeted: the hook "*" has no class under hooks in spec/budgets.yaml`,
	}
	got := strings.Join(found, "\n")
	for _, w := range want {
		if !strings.Contains(got, w) {
			t.Errorf("found lacks %q:\n%s", w, got)
		}
	}
	if len(found) != len(want) {
		t.Errorf("found %d, want %d:\n%s", len(found), len(want), got)
	}
}

func TestBudgetsWithoutCommandsCheckOnlyTheirClasses(t *testing.T) {
	t.Parallel()
	if found := check(t, "budgeted", map[string]string{"spec/budgets.yaml": budgetsYAML}); len(found) != 1 {
		t.Errorf("found:\n%s", strings.Join(found, "\n"))
	}
}
