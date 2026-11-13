package fleet_test

import (
	"testing"
	"time"

	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/kern/kerntest"
	"github.com/mb-89/se/components/fleet"
)

func issue(n int, title string, labels ...any) github.Snapshot {
	return github.Snapshot{Repo: "alice/demo", Number: n, Via: github.Relay,
		Data: map[string]any{"number": float64(n), "title": title, "state": "open", "labels": labels}}
}

// Against the fake core, the derivation reads the GitHub families whole and
// the lease from its config: nothing read is no verdict, in-progress work
// with a quiet branch is a finding, and the output says how much it read.
func TestTheFleetDerivesFromTheNamesAlone(t *testing.T) {
	nine := time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC)
	fleet.Now = func() time.Time { return nine }
	f, err := kerntest.New(fleet.Component)
	if err != nil {
		t.Fatal(err)
	}
	if err := f.Derive("findings"); err != nil {
		t.Fatal(err)
	}
	v, _ := f.Out("findings")
	if got := v.V.(fleet.Findings); got.Healthy || got.Complete || got.Issues != 0 || len(got.Findings) != 0 {
		t.Fatalf("with nothing read the findings are %+v, and want no verdict over 0 issues", got)
	}
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	must(f.Seed("issues", map[string]github.Snapshot{"alice.demo.4": issue(4, "feat/x", "in-progress")}))
	must(f.Seed("branches", map[string]time.Time{"feat/x": nine.Add(-2 * time.Hour)}))
	must(f.Config("lease-hours", 1.5))
	must(f.Derive("findings"))
	v, _ = f.Out("findings")
	got := v.V.(fleet.Findings)
	if got.Healthy || len(got.Findings) != 1 || got.Findings[0].Kind != "quiet branch" ||
		got.Findings[0].What != "no push to feat/x for 2 hours, over the lease of 1.5" || !got.At.Equal(nine) {
		t.Fatalf("the findings are %+v, and want #4's quiet branch over the lease of 1.5", got)
	}
}

func TestBlockersReadTheBodyAndTheRoutedSection(t *testing.T) {
	body := "## Blocked by\n\n#3, a/#4, x#5, #6b <!-- #7 -->\n\n## Routing\n\n### Blocked by\n\n- #8\n"
	if got := fleet.Blockers(body); len(got) != 2 || got[0] != 3 || got[1] != 8 {
		t.Fatalf("the blockers are %v, and want [3 8]", got)
	}
}

// A partial view is not a verdict: single snapshots without the open lists
// are not healthy, and say how much was seen and since when; the open issue
// and pull-request lists, each read whole, make the same fleet healthy.
func TestOnlyACompleteReadOfTheOpenListsIsHealthy(t *testing.T) {
	nine := time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC)
	fleet.Now = func() time.Time { return nine }
	f, err := kerntest.New(fleet.Component)
	if err != nil {
		t.Fatal(err)
	}
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	seen := issue(4, "feat/x")
	seen.Read = nine.Add(-30 * time.Minute)
	must(f.Seed("issues", map[string]github.Snapshot{"alice.demo.4": seen}))
	must(f.Config("repository", "demo"))
	must(f.Derive("findings"))
	v, _ := f.Out("findings")
	if got := v.V.(fleet.Findings); got.Healthy || got.Complete || got.Issues != 1 || !got.Since.Equal(seen.Read) {
		t.Fatalf("on one issue read the findings are %+v, and want no verdict over 1 issue since %s", got, seen.Read)
	}
	// A labelled list, or another repository's, is no read of the open fleet.
	list := func(repo string, at time.Time, labels ...string) github.List {
		return github.List{Repo: repo, State: "open", Labels: labels, Read: at, Via: github.Relay, Data: []any{}}
	}
	must(f.Seed("issue-lists", map[string]github.List{"alice.demo.open.work": list("alice/demo", nine, "work"),
		"bob.other.open": list("bob/other", nine)}))
	must(f.Seed("pull-lists", map[string]github.List{"alice.demo.open": list("alice/demo", nine.Add(-time.Hour))}))
	must(f.Derive("findings"))
	v, _ = f.Out("findings")
	if got := v.V.(fleet.Findings); got.Healthy || got.Complete {
		t.Fatalf("without the open issues' whole list the findings are %+v, and want no verdict", got)
	}
	must(f.Seed("issue-lists", map[string]github.List{"alice.demo.open": list("alice/demo", nine.Add(-10*time.Minute))}))
	must(f.Derive("findings"))
	v, _ = f.Out("findings")
	if got := v.V.(fleet.Findings); !got.Healthy || !got.Complete || !got.Since.Equal(nine.Add(-time.Hour)) {
		t.Fatalf("on both open lists the findings are %+v, and want healthy since the older read", got)
	}
}
