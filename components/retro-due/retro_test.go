package retrodue_test

import (
	"strconv"
	"testing"
	"time"

	"kern/components/github"
	"kern/kerntest"
	retrodue "se/components/retro-due"
)

// Against the fake core: a retro is due once what came back after the newest
// retro started weighs due-after.
func TestARetroIsDueOnceEnoughWorkLanded(t *testing.T) {
	retrodue.Now = func() time.Time { return time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC) }
	defer func() { retrodue.Now = time.Now }()
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
		if got := v.V.(retrodue.Due); got.Landed != 1 || got.Count != 1 || got.Due != want || got.Retro != 1 {
			t.Fatalf("due after %d: %+v, and wants 1 landed since retro #1, due %v", due, got, want)
		}
		// The overhaul countdown is on by default (3 retros, 30 days): one retro is not due.
		if got := v.V.(retrodue.Due); got.OverhaulAfter != 3 || got.OverhaulDays != 30 || got.OverhaulDue || got.Retros != 1 {
			t.Fatalf("overhaul by default: %+v, and wants 1 retro counted, on and not due", got)
		}
	}
}

// An overhaul is due once overhaul-after retros closed since the newest
// overhaul started (here: closed, the names giving no creation), and the next
// overhaul resets the countdown; a retro closed as a duplicate or not planned
// counts no more than a landing would; with overhaul-after 0 and no
// overhaul-days the countdown is never due.
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
	now := time.Date(2026, 11, 6, 0, 0, 0, 0, time.UTC)
	if got := retrodue.Count(in, now); got.Retros != 2 || got.OverhaulDue || got.Overhaul != 1 || got.OverhaulSince != "2026-10-01T00:00:00Z" {
		t.Fatalf("after two retros: %+v, and wants 2 retros since overhaul #1, not due", got)
	}
	issues["alice.demo.6"] = issue(6, "docs/retro-20261101", "2026-11-01T00:00:00Z", "completed")
	if got := retrodue.Count(in, now); got.Retros != 3 || !got.OverhaulDue {
		t.Fatalf("after the third retro: %+v, and wants 3 retros, an overhaul due", got)
	}
	off := in
	off.OverhaulAfter = 0
	if got := retrodue.Count(off, now); got.Retros != 3 || got.OverhaulDue {
		t.Fatalf("switched off: %+v, and wants 3 retros counted, not due", got)
	}
	issues["alice.demo.7"] = issue(7, "docs/overhaul-20261102", "2026-11-02T00:00:00Z", "completed")
	if got := retrodue.Count(in, now); got.Retros != 0 || got.OverhaulDue || got.Overhaul != 7 {
		t.Fatalf("after the next overhaul: %+v, and wants 0 retros since overhaul #7, not due", got)
	}
	// A ticket named like an overhaul is none; an overhaul under the name rule is one.
	issues["alice.demo.8"] = issue(8, "docs/retro-20261103", "2026-11-03T00:00:00Z", "completed")
	issues["alice.demo.9"] = issue(9, "overhaul-the-docs", "2026-11-04T00:00:00Z", "completed")
	if got := retrodue.Count(in, now); got.Retros != 1 || got.Overhaul != 7 {
		t.Fatalf("after a ticket named overhaul-the-docs: %+v, and wants overhaul #7 still", got)
	}
	issues["alice.demo.10"] = issue(10, "overhaul-20261105", "2026-11-05T00:00:00Z", "completed")
	if got := retrodue.Count(in, now); got.Retros != 0 || got.Overhaul != 10 {
		t.Fatalf("after overhaul-20261105: %+v, and wants 0 retros since overhaul #10", got)
	}
}

// Opening issues counts nothing; 20 that come back make a retro due, a
// failure weighs failure-weight, 7 days with anything come back make one due,
// and the newest retro's start, open or closed, resets the count.
func TestWhatComesBackMakesARetroDueAndItsStartResetsIt(t *testing.T) {
	issues := map[string]github.Snapshot{}
	pulls := map[string]github.Snapshot{}
	add := func(n int, d map[string]any) {
		d["number"] = float64(n)
		issues["alice.demo."+strconv.Itoa(n)] = github.Snapshot{Repo: "alice/demo", Number: n, Data: d}
	}
	add(1, map[string]any{"title": "retro-due-20261101", "labels": []any{"retro"}, "state": "closed",
		"created_at": "2026-11-01T00:00:00Z", "closed_at": "2026-11-02T00:00:00Z"})
	for n := 10; n < 30; n++ {
		add(n, map[string]any{"title": "n", "state": "open", "labels": []any{"work"}, "created_at": "2026-11-10T00:00:00Z"})
	}
	in := retrodue.In{Issues: issues, Pulls: pulls, DueAfter: 20, FailureWeight: 5, Days: 7, Base: "main"}
	now := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	if got := retrodue.Count(in, now); got.Count != 0 || got.Due {
		t.Fatalf("20 opened: %+v, and wants nothing counted, not due", got)
	}
	for n := 10; n < 30; n++ {
		add(n, map[string]any{"title": "n", "state": "closed", "labels": []any{"work"}, "closed_at": "2026-11-05T00:00:00Z"})
		pulls["alice.demo."+strconv.Itoa(100+n)] = github.Snapshot{Repo: "alice/demo", Number: 100 + n, Data: map[string]any{
			"number": float64(100 + n), "body": "Fixes #" + strconv.Itoa(n), "state": "closed",
			"merged_at": "2026-11-05T00:00:00Z", "base": map[string]any{"ref": "main"}}}
	}
	if got := retrodue.Count(in, now); got.Landed != 20 || !got.Due || got.Reason != "20 came back since the last retro (due at 20)" {
		t.Fatalf("20 came back: %+v, and wants a retro due", got)
	}
	add(2, map[string]any{"title": "retro-due-20261106", "labels": []any{"retro"}, "state": "open", "created_at": "2026-11-06T00:00:00Z"})
	if got := retrodue.Count(in, now); got.Count != 0 || got.Due || got.Retro != 2 || len(got.Open) != 1 || got.Open[0] != 2 {
		t.Fatalf("after the retro started: %+v, and wants the count reset, retro #2 open", got)
	}
	add(40, map[string]any{"title": "x", "state": "open", "labels": []any{"work", "escalated"}, "updated_at": "2026-11-07T00:00:00Z"})
	if got := retrodue.Count(in, now); got.Failed != 1 || got.Count != 5 || !got.Due ||
		got.Reason != "14 days since the last retro with 5 came back (due after 7 days)" {
		t.Fatalf("a failure 14 days on: %+v, and wants it weighed 5 and a retro due by days", got)
	}
}
