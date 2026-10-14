package issues_test

import (
	"testing"

	"github.com/mb-89/SE/src/internal/issues"
)

func TestEachKindNamesItsAgent(t *testing.T) {
	t.Parallel()
	for _, c := range []struct {
		issue issues.Issue
		agent string
	}{
		{issues.Issue{Number: 1}, "se:worker"},
		{issues.Issue{Number: 2, Parent: true}, "se:coordinator"},
		{issues.Issue{Number: 3, Retro: true}, "se:retro"},
		{issues.Issue{Number: 4, Overhaul: true}, "se:overhaul"},
	} {
		if got := issues.KindOf(c.issue).Type(); got != c.agent {
			t.Errorf("#%d: %s, want %s", c.issue.Number, got, c.agent)
		}
	}
	if k := issues.KindNamed("gate"); k.Type() != "se:reviewer" || k.File() != "src/plugin/agents/reviewer.md" {
		t.Errorf("a gate: %+v", k)
	}
	// Every kind has an agent of its own, and no role is held twice.
	if agents := issues.Agents(); len(agents) != len(issues.IssueKinds) {
		t.Errorf("%d kinds share %d agents", len(issues.IssueKinds), len(agents))
	}
	// A role, or an agent's name, is no skill.
	if got := issues.Skills([]string{"overhaul", "triage", "retro", "work", "reviewer"}); len(got) != 1 || got[0] != "triage" {
		t.Errorf("the skills of a line naming roles: %v", got)
	}
	if k, ok := issues.RoleNamed("coordination"); !ok || k.Agent != "coordinator" {
		t.Errorf("coordination: %+v %v", k, ok)
	}
}
