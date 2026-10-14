package github_test

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/github"
)

// limited is a fake GitHub holding issue #1 of o/r, and the module living
// within its limits on the same fake clock, saying its waits on said.
func limited(t *testing.T, l github.Limits) (*github.Fake, *github.Limited, *clock.Fake, *strings.Builder) {
	t.Helper()
	c := clock.NewFake(start)
	f := github.NewFake(c)
	if _, err := f.Send("POST", "repos/o/r/issues", github.F("title", "one")); err != nil {
		t.Fatal(err)
	}
	said := &strings.Builder{}
	return f, github.Limit(f, c, l, said), c, said
}

// A spent quota makes the module say so, wait for the reset and ask again,
// once, rather than hammer GitHub while it refuses.
func TestARateLimitIsWaitedOutUntilTheReset(t *testing.T) {
	t.Parallel()
	f, gh, c, said := limited(t, github.Limits{Ceiling: time.Hour})
	f.Quota(3, time.Hour) // the window opens at the next request
	for range 3 {
		if _, err := gh.Get("repos/o/r/issues/1"); err != nil {
			t.Fatal(err)
		}
	}
	before := f.Requests()
	if r := gh.Rate(); !r.Known || r.Limit != 3 || r.Remaining != 0 || !r.Reset.Equal(start.Add(time.Hour)) {
		t.Fatalf("after the hour's 3 requests the quota reads %+v", r)
	}
	out, err := gh.Get("repos/o/r/issues/1")
	if err != nil || !strings.Contains(string(out), `"title":"one"`) {
		t.Fatalf("after the reset: %s %v", out, err)
	}
	if n := f.Requests() - before; n != 2 {
		t.Fatalf("the module asked %d times, want 2: the refused one and the one after the reset", n)
	}
	if want := start.Add(time.Hour); !c.Now().Equal(want) {
		t.Fatalf("the module waited until %s, want the reset, %s", c.Now(), want)
	}
	if want := "se: GitHub refused a request for its rate limit (HTTP 403); waiting 1h0m0s, until 13:00:00 UTC, for it to reset.\n"; said.String() != want {
		t.Fatalf("it said %q, want %q", said.String(), want)
	}
}

// A reset further off than the ceiling fails the request at once, naming
// when the reset comes, rather than waiting for nothing.
func TestAResetPastTheCeilingFailsAtOnce(t *testing.T) {
	t.Parallel()
	f, gh, c, said := limited(t, github.Limits{Ceiling: 10 * time.Minute})
	f.Quota(1, time.Hour)
	if _, err := gh.Get("repos/o/r/issues/1"); err != nil {
		t.Fatal(err)
	}
	before := f.Requests()
	_, err := gh.Get("repos/o/r/issues/1")
	if err == nil || github.Status(err) != 403 || !strings.Contains(err.Error(), "holds until 13:00:00 UTC, past the 10m0s se waits for it") {
		t.Fatalf("%v", err)
	}
	if n := f.Requests() - before; n != 1 || !c.Now().Equal(start) || said.Len() != 0 {
		t.Fatalf("it asked %d times, waited until %s and said %q", n, c.Now(), said.String())
	}
}

// A secondary limit's retry-after is waited out, and a 403 that names no
// rate limit is no reason to wait.
func TestASecondaryLimitIsWaitedOutAndAPermissionIsNot(t *testing.T) {
	t.Parallel()
	f, gh, c, said := limited(t, github.Limits{Ceiling: time.Hour})
	f.ContentLimit(2, time.Minute)
	for k := range 3 {
		if _, err := gh.Send("POST", "repos/o/r/issues/1/comments", github.F("body", fmt.Sprint(k))); err != nil {
			t.Fatal(err)
		}
	}
	if !c.Now().Equal(start.Add(time.Minute)) || !strings.Contains(said.String(), "waiting 1m0s") {
		t.Fatalf("the third comment waited until %s, saying %q", c.Now(), said.String())
	}
	if _, limited := github.RateLimited(&github.Error{Status: 403, Message: "gh: Resource not accessible by integration"}); limited {
		t.Fatal("a refused permission reads as a rate limit")
	}
}

// Fifty comments in a row go out spaced by the write spacing, one at a
// time, and so stay under GitHub's limit on creating content: none is
// refused.
func TestFiftyCommentsInARowAreSpaced(t *testing.T) {
	t.Parallel()
	f, gh, c, said := limited(t, github.Limits{Ceiling: time.Hour, Spacing: 2 * time.Second})
	// GitHub's content limit, made tighter than its 80 a minute: 30 a minute.
	f.ContentLimit(30, time.Minute)
	for k := range 50 {
		if _, err := gh.Send("POST", "repos/o/r/issues/1/comments", github.F("body", fmt.Sprint(k))); err != nil {
			t.Fatal(err)
		}
	}
	if said.Len() != 0 {
		t.Fatalf("a spaced comment was refused: %s", said.String())
	}
	out, err := gh.List("repos/o/r/issues/1/comments?per_page=100")
	if err != nil {
		t.Fatal(err)
	}
	var comments []struct {
		CreatedAt time.Time `json:"created_at"`
	}
	if err := json.Unmarshal(out, &comments); err != nil || len(comments) != 50 {
		t.Fatalf("%d comments: %v", len(comments), err)
	}
	for k := 1; k < len(comments); k++ {
		if gap := comments[k].CreatedAt.Sub(comments[k-1].CreatedAt); gap < 2*time.Second {
			t.Fatalf("comments %d and %d are %s apart, under the spacing", k-1, k, gap)
		}
	}
	if want := start.Add(49 * 2 * time.Second); !c.Now().Equal(want) {
		t.Fatalf("fifty comments took until %s, want %s", c.Now(), want)
	}
}

// The quota floor says when the hour's requests run low, and nothing before.
func TestTheQuotaRunsLowBelowTheFloor(t *testing.T) {
	t.Parallel()
	reset := start.Add(time.Hour)
	if s := (github.Rate{Known: true, Limit: 15000, Remaining: 3000, Reset: reset}).Low(20); s != "" {
		t.Fatalf("at the floor: %q", s)
	}
	if s := (github.Rate{}).Low(20); s != "" {
		t.Fatalf("an unknown quota: %q", s)
	}
	want := "GitHub's quota runs low: 2999 of the hour's 15000 requests left, under the 20% floor (github/config/quota-floor), until it resets at 13:00 UTC; the fleet shares it, so pace what can wait"
	if s := (github.Rate{Known: true, Limit: 15000, Remaining: 2999, Reset: reset}).Low(20); s != want {
		t.Fatalf("%q", s)
	}
}
