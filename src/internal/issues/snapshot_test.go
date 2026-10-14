// Internal test package: it reads through the package's test fakes and its
// links paths, as the other internal tests do.
package issues

import (
	"fmt"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// counting is GitHub that lists which links paths were read through it.
type counting struct {
	github.GitHub
	mu    sync.Mutex
	links []string
}

func (c *counting) List(path string) ([]byte, error) {
	if strings.Contains(path, "/dependencies/blocked_by") {
		c.mu.Lock()
		c.links = append(c.links, path)
		c.mu.Unlock()
	}
	return c.GitHub.List(path)
}

func (c *counting) read() []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := slices.Clone(c.links)
	slices.Sort(out)
	c.links = nil
	return out
}

// An issue unchanged for longer than the settle time whose summary counts
// no link has its links left unread; one just linked is read, though its
// summary still counts nothing, and stays blocked.
func TestASettledSummaryStandsForTheLinksAndAFreshOneDoesNot(t *testing.T) {
	t.Parallel()
	clk := atNow()
	gh := recordedAt(t, clk, map[string]string{
		listPath: `[{"id":105,"number":5,"title":"t5","state":"open","updated_at":"2026-10-13T09:00:00Z"},` +
			`{"id":106,"number":6,"title":"t6","state":"open","updated_at":"2026-10-13T09:00:00Z"}]`,
		refsPath: `[]`,
	})
	c := &counting{GitHub: gh}
	s := Source{Proc: machine, Repo: repo, GitHub: c, Clock: clk}
	if next, ok, err := s.Next(); err != nil || !ok || next.Number != 5 {
		t.Fatalf("next = %+v %v %v", next, ok, err)
	}
	if got := c.read(); len(got) != 0 {
		t.Fatalf("settled issues with no links had them read: %v", got)
	}
	// #5 is linked as blocked by #6 now: its summary lags, but it changed.
	if _, err := gh.Send("POST", "repos/o/r/issues/5/dependencies/blocked_by", github.Int("issue_id", 106)); err != nil {
		t.Fatal(err)
	}
	all, err := s.Survey()
	if err != nil {
		t.Fatal(err)
	}
	if all[0].Why != "blocked by #6" {
		t.Fatalf("#5: %q", all[0].Why)
	}
	if got := c.read(); !slices.Equal(got, []string{links(5)}) {
		t.Fatalf("read the links of %v", got)
	}
	// Settled, the summary counts the link, so the links are still read.
	clk.Advance(Settle)
	if all, err = s.Survey(); err != nil || all[0].Why != "blocked by #6" {
		t.Fatalf("#5: %+v %v", all, err)
	}
	if got := c.read(); !slices.Equal(got, []string{links(5)}) {
		t.Fatalf("read the links of %v", got)
	}
}

// A pull answers from the daemon's snapshot without asking GitHub; a take
// from it re-reads, from GitHub, whether the issue it claims is still open
// and unblocked, and moves on where it is not.
func TestATakeFromASnapshotReReadsWhatItsClaimMustBeSureOf(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	gh := recorded(t, unblocked(map[string]string{
		listPath: `[{"id":105,"number":5,"title":"t5","state":"open"},{"id":106,"number":6,"title":"t6","state":"open"},` +
			`{"id":107,"number":7,"title":"t7","state":"open"}]`,
		refsPath: `[]`,
	}, 5, 6, 7))
	live := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	snap, err := Warm(live)
	if err != nil {
		t.Fatal(err)
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("the snapshot wrote %v", w)
	}
	warm := live
	warm.GitHub = github.Replay(snap, never{t})
	next, ok, cads, err := warm.Pull()
	if err != nil || !ok || next.Number != 5 || len(cads) != 2 {
		t.Fatalf("pull = %+v %v %+v %v", next, ok, cads, err)
	}
	// After the snapshot, #5 is blocked by #7 and #6 closes.
	if _, err := gh.Send("POST", "repos/o/r/issues/5/dependencies/blocked_by", github.Int("issue_id", 107)); err != nil {
		t.Fatal(err)
	}
	if _, err := gh.Send("PATCH", "repos/o/r/issues/6", github.F("state", "closed")); err != nil {
		t.Fatal(err)
	}
	warm.GitHub, warm.Live = github.Replay(snap, gh), gh
	if _, _, err := warm.Take(a, 5); err == nil || !strings.Contains(err.Error(), "#5 is not ready") {
		t.Fatalf("taking #5: %v", err)
	}
	took, ok, err := warm.Take(a, 0)
	if err != nil || !ok || took.Number != 7 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
	if got := run(t, a, "rev-parse", "--abbrev-ref", "HEAD"); got != fmt.Sprintf("issue-%d", 7) {
		t.Fatalf("a is on %s", got)
	}
}
