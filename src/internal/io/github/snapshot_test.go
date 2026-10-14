package github_test

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/github"
)

// A recording reads through and keeps each answer, refuses every write, and
// a replay answers what it kept without asking again, every other read and
// every write from the live GitHub.
func TestASnapshotIsReadOnceAndAnsweredFrom(t *testing.T) {
	t.Parallel()
	f := seeded(t, map[string]string{"repos/o/r/issues/1": `{"number":1,"title":"one","state":"open"}`})
	rec := github.Record(f)
	if _, err := rec.Get("repos/o/r/issues/1"); err != nil {
		t.Fatal(err)
	}
	if _, err := rec.List("repos/o/r/issues?state=open&per_page=100"); err != nil {
		t.Fatal(err)
	}
	if _, err := rec.Send("PATCH", "repos/o/r/issues/1", github.F("title", "two")); !errors.Is(err, github.ErrReadOnly) {
		t.Fatalf("a write through a recording: %v", err)
	}
	if w := f.Writes(); len(w) != 0 {
		t.Fatalf("a recording wrote %v", w)
	}
	snap := rec.Snapshot("o/r", start)
	if !snap.Taken() || len(snap.Answers) != 2 || snap.Repo != "o/r" || !snap.At.Equal(start) {
		t.Fatalf("%+v", snap)
	}
	// GitHub moves on; the replay still answers what the snapshot holds.
	if _, err := f.Send("PATCH", "repos/o/r/issues/1", github.F("title", "two")); err != nil {
		t.Fatal(err)
	}
	r := github.Replay(snap, f)
	if out, err := r.Get("repos/o/r/issues/1"); err != nil || !strings.Contains(string(out), `"one"`) {
		t.Fatalf("%s %v", out, err)
	}
	if out, err := r.Get("repos/o/r/issues/1?fresh=1"); err != nil || !strings.Contains(string(out), `"two"`) {
		t.Fatalf("a read the snapshot lacks: %s %v", out, err)
	}
	if _, err := r.Send("PATCH", "repos/o/r/issues/1", github.F("title", "three")); err != nil || len(f.Writes()) != 2 {
		t.Fatalf("a write through a replay: %v %v", err, f.Writes())
	}
}

// The keeper reads a snapshot when the daemon starts, again once its
// refresh has passed, and at once when it is told the snapshot is stale.
func TestTheKeeperKeepsTheSnapshotWarm(t *testing.T) {
	t.Parallel()
	w, err := index.Wired()
	if err != nil {
		t.Fatal(err)
	}
	own := index.Wiring{}
	for _, in := range w.Instances {
		if in.Module == github.Module.Name() {
			own.Instances = append(own.Instances, in)
		}
	}
	ix, err := index.Start(own, github.Module)
	if err != nil {
		t.Fatal(err)
	}
	clk := clock.NewFake(start)
	reads := 0
	kept := make(chan github.Snapshot)
	k := github.NewKeeper(func(set github.Settings) (github.Snapshot, error) {
		if set.Refresh != 2*time.Minute || set.Settle != 5*time.Minute {
			t.Errorf("the keeper read %+v", set)
		}
		reads++
		return github.Snapshot{Repo: "o/r", At: clk.Now(), Answers: map[string]string{"GET x": "1"}}, nil
	}, clk, func(s string) { t.Error(s) })
	k.Kept = func(s github.Snapshot) { kept <- s }
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { k.Keep(ctx, ix); close(done) }()
	defer func() { cancel(); <-done }()
	<-kept
	v, err := ix.Read(k.Name())
	if err != nil || !v.Provided || !v.V.(github.Snapshot).Taken() {
		t.Fatalf("%s = %+v %v", k.Name(), v, err)
	}
	if k.Stale("other/name") {
		t.Fatal("the keeper took another name as its own")
	}
	if !k.Stale(k.Name()) {
		t.Fatal("the keeper did not take its own name")
	}
	<-kept
	clk.Advance(2 * time.Minute)
	if s := <-kept; !s.At.Equal(start.Add(2 * time.Minute)) {
		t.Fatalf("the refresh read at %v", s.At)
	}
	if reads != 3 {
		t.Fatalf("%d reads", reads)
	}
}

// The fake's dependency summary leaves out a link written less than
// SummaryLag ago, as GitHub's can; the links never lag.
func TestTheFakeDependencySummaryLagsALinkJustWritten(t *testing.T) {
	t.Parallel()
	clk := clock.NewFake(start)
	f := github.NewFake(clk)
	for _, title := range []string{"one", "two"} {
		if _, err := f.Send("POST", "repos/o/r/issues", github.F("title", title)); err != nil {
			t.Fatal(err)
		}
	}
	one := get[issue](t, f, "repos/o/r/issues/1")
	if _, err := f.Send("POST", "repos/o/r/issues/2/dependencies/blocked_by", github.Int("issue_id", one.ID)); err != nil {
		t.Fatal(err)
	}
	if got := summaryOf(t, f, 2); got != "0/0" {
		t.Fatalf("right after the link the summary counts %s", got)
	}
	clk.Advance(github.SummaryLag)
	if got := summaryOf(t, f, 2); got != "1/1" {
		t.Fatalf("after the lag the summary counts %s", got)
	}
	if _, err := f.Send("PATCH", "repos/o/r/issues/1", github.F("state", "closed")); err != nil {
		t.Fatal(err)
	}
	if got := summaryOf(t, f, 2); got != "0/1" {
		t.Fatalf("with its blocker closed the summary counts %s", got)
	}
}

// summaryOf is issue n's summary as open blockers/all blockers.
func summaryOf(t *testing.T, f github.GitHub, n int) string {
	t.Helper()
	got := get[struct {
		S struct {
			BlockedBy int `json:"blocked_by"`
			Total     int `json:"total_blocked_by"`
		} `json:"issue_dependencies_summary"`
	}](t, f, fmt.Sprintf("repos/o/r/issues/%d", n))
	return fmt.Sprintf("%d/%d", got.S.BlockedBy, got.S.Total)
}
