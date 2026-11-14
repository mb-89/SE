package retrodue_test

import (
	"testing"

	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/kern/kerntest"
	retrodue "github.com/mb-89/se/components/retro-due"
)

// Against the fake core: a retro is due once due-after work issues landed
// after the last retro closed.
func TestARetroIsDueOnceEnoughWorkLanded(t *testing.T) {
	f, err := kerntest.New(retrodue.Component)
	if err != nil {
		t.Fatal(err)
	}
	snap := func(n int, d map[string]any) github.Snapshot {
		d["number"] = float64(n)
		return github.Snapshot{Repo: "alice/demo", Number: n, Data: d}
	}
	issues := map[string]github.Snapshot{
		"alice.demo.1": snap(1, map[string]any{"title": "docs/retro-1", "state": "closed", "closed_at": "2026-11-01T00:00:00Z"}),
		"alice.demo.2": snap(2, map[string]any{"title": "feat/a", "state": "closed", "closed_at": "2026-11-02T00:00:00Z", "labels": []any{"work"}}),
		"alice.demo.3": snap(3, map[string]any{"title": "feat/b", "state": "closed", "closed_at": "2026-10-02T00:00:00Z", "labels": []any{"work"}}),
	}
	pulls := map[string]github.Snapshot{
		"alice.demo.12": snap(12, map[string]any{"body": "Fixes #2", "state": "closed", "merged_at": "2026-11-02T00:00:00Z", "base": map[string]any{"ref": "main"}}),
		"alice.demo.13": snap(13, map[string]any{"body": "Fixes #3", "state": "closed", "merged_at": "2026-10-02T00:00:00Z", "base": map[string]any{"ref": "main"}}),
	}
	for port, v := range map[string]any{"issues": issues, "pulls": pulls} {
		if err := f.Seed(port, v); err != nil {
			t.Fatal(err)
		}
	}
	for due, want := range map[int]bool{1: true, 2: false} {
		if err := f.Config("due-after", due); err != nil {
			t.Fatal(err)
		}
		if err := f.Derive("due"); err != nil {
			t.Fatal(err)
		}
		v, _ := f.Out("due")
		if got := v.V.(retrodue.Due); got.Landed != 1 || got.Due != want || got.Retro != 1 {
			t.Fatalf("due after %d: %+v, and wants 1 landed since retro #1, due %v", due, got, want)
		}
		// The overhaul countdown is off by default: it counts, and is never due.
		if got := v.V.(retrodue.Due); got.OverhaulAfter != 0 || got.OverhaulDue || got.Retros != 1 {
			t.Fatalf("overhaul by default: %+v, and wants 1 retro counted, off and not due", got)
		}
	}
}

// An overhaul is due once overhaul-after retros closed since the last
// overhaul closed, and the next overhaul resets the countdown; a retro closed
// as a duplicate or not planned counts no more than a landing would; with
// overhaul-after 0 the countdown is off and never due.
func TestAnOverhaulIsDueAfterTheThirdRetroAndResetsWithAnOverhaul(t *testing.T) {
	issue := func(n int, title, closed, reason string) github.Snapshot {
		d := map[string]any{"number": float64(n), "title": title, "state": "closed", "closed_at": closed, "state_reason": reason}
		return github.Snapshot{Repo: "alice/demo", Number: n, Data: d}
	}
	issues := map[string]github.Snapshot{
		"alice.demo.1": issue(1, "docs/overhaul-20261001", "2026-10-01T00:00:00Z", "completed"),
		"alice.demo.2": issue(2, "docs/retro-20260920", "2026-09-20T00:00:00Z", "completed"),
		"alice.demo.3": issue(3, "docs/retro-20261010", "2026-10-10T00:00:00Z", "completed"),
		"alice.demo.4": issue(4, "docs/retro-20261020", "2026-10-20T00:00:00Z", "completed"),
		"alice.demo.5": issue(5, "docs/retro-20261021", "2026-10-21T00:00:00Z", "duplicate"),
	}
	in := retrodue.In{Issues: issues, DueAfter: 10, OverhaulAfter: 3, Base: "main"}
	if got := retrodue.Count(in); got.Retros != 2 || got.OverhaulDue || got.Overhaul != 1 || got.OverhaulSince != "2026-10-01T00:00:00Z" {
		t.Fatalf("after two retros: %+v, and wants 2 retros since overhaul #1, not due", got)
	}
	issues["alice.demo.6"] = issue(6, "docs/retro-20261101", "2026-11-01T00:00:00Z", "completed")
	if got := retrodue.Count(in); got.Retros != 3 || !got.OverhaulDue {
		t.Fatalf("after the third retro: %+v, and wants 3 retros, an overhaul due", got)
	}
	off := in
	off.OverhaulAfter = 0
	if got := retrodue.Count(off); got.Retros != 3 || got.OverhaulDue {
		t.Fatalf("switched off: %+v, and wants 3 retros counted, not due", got)
	}
	issues["alice.demo.7"] = issue(7, "docs/overhaul-20261102", "2026-11-02T00:00:00Z", "completed")
	if got := retrodue.Count(in); got.Retros != 0 || got.OverhaulDue || got.Overhaul != 7 {
		t.Fatalf("after the next overhaul: %+v, and wants 0 retros since overhaul #7, not due", got)
	}
}
