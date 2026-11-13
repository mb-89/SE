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
	}
}
