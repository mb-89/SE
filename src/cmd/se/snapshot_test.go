// Internal test package: package main cannot be imported.
package main

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/issues"
)

// offline is GitHub out of reach: every call fails.
type offline struct{}

var errOffline = errors.New("GitHub is out of reach")

func (offline) Get(string) ([]byte, error)                           { return nil, errOffline }
func (offline) List(string) ([]byte, error)                          { return nil, errOffline }
func (offline) Send(string, string, ...github.Field) ([]byte, error) { return nil, errOffline }
func (offline) GraphQL(string, ...github.Field) ([]byte, error)      { return nil, errOffline }

// With the workspace's daemon warm, se issue pull answers from its snapshot
// of GitHub and asks GitHub nothing; once the snapshot is older than its
// refresh, the answer says how old it is.
func TestIssuePullAnswersFromTheDaemonsWarmSnapshot(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	onFake(t)
	ws := "/ws"
	kept := warmDaemon(t, ws, gh)
	<-kept
	cold := "#3 three\nu3\n\ndo it\n\n1 se issue closed and no retro has closed yet; a retro is due at 10.\n\n0 retros closed and no overhaul has closed yet; an overhaul is due at 5.\n"
	worldOf(t).GitHub = offline{}
	code, out, errs := se(t, "issue", "pull", "--repo", "o/r", "--workspace", ws)
	if code != 0 || out != cold {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	// Another repository is no part of the snapshot: it is read from GitHub.
	if code, _, errs = se(t, "issue", "pull", "--repo", "o/other", "--workspace", ws); code == 0 || !strings.Contains(errs, errOffline.Error()) {
		t.Fatalf("exit %d, %q", code, errs)
	}
	worldOf(t).Clock.(*clock.Fake).Advance(3 * time.Minute)
	code, out, errs = se(t, "issue", "pull", "--repo", "o/r", "--workspace", ws)
	if want := strings.TrimRight(cold, "\n") + "\n\nAnswered from the daemon's snapshot of GitHub, 3m0s old.\n"; code != 0 || out != want {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	// A command that writes to GitHub tells the daemon, which reads again at once.
	worldOf(t).GitHub = gh
	if code, _, errs = se(t, "issue", "new", "--repo", "o/r", "--workspace", ws, "--title", "four", "--body", "b", "--blocked-by", "none"); code != 0 {
		t.Fatalf("exit %d, %q", code, errs)
	}
	if snap := <-kept; !strings.Contains(snap.Answers["GET repos/o/r/issues?labels=se&state=open&per_page=100&page=1"], `"four"`) {
		t.Fatalf("the snapshot after the write: %v", snap.Answers)
	}
}

// warmDaemon serves the workspace ws's daemon on the test's network and disk
// until the test ends, its keeper reading the snapshot of o/r from gh on a
// clock of its own. It answers each snapshot the keeper commits.
func warmDaemon(t *testing.T, ws string, gh github.GitHub) <-chan github.Snapshot {
	t.Helper()
	w := worldOf(t)
	keeperClock := clock.NewFake(testedAt)
	k := github.NewKeeper(func(set github.Settings) (github.Snapshot, error) {
		return issues.Warm(issues.Source{Repo: "o/r", GitHub: gh, Clock: keeperClock, Settle: set.Settle})
	}, keeperClock, func(s string) { t.Error(s) })
	kept := make(chan github.Snapshot, 4)
	k.Kept = func(s github.Snapshot) { kept <- s }
	paths := daemon.Paths{Workspace: ws, Disk: w.Disk}
	ctx, stop := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- daemon.Serve(ctx, paths, daemon.Options{
			Clock: w.Clock, Net: w.Net, Modules: modules(paths, w.Clock), Keepers: []daemon.Keeper{k},
		})
	}()
	t.Cleanup(func() {
		stop()
		<-done
	})
	return kept
}
