// Internal test package: it reads through the package's test fakes, as the
// other internal tests do.
package issues

import (
	"fmt"
	"runtime"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/mb-89/SE/src/internal/io/github"
)

// heldBack is GitHub that holds back each read hold names (list is set for
// a List, which reads every page) until a read whose path holds first has
// been asked, or the reads already started had their turn: the held read
// then fails, so a test sees which read waited on which.
type heldBack struct {
	github.GitHub
	hold  func(path string, list bool) bool
	first string
	once  sync.Once
	seen  chan struct{}
}

func waitFor(gh github.GitHub, hold func(path string, list bool) bool, first string) *heldBack {
	return &heldBack{GitHub: gh, hold: hold, first: first, seen: make(chan struct{})}
}

// holds is a hold on every read of a path that holds part.
func holds(part string) func(string, bool) bool {
	return func(path string, _ bool) bool { return strings.Contains(path, part) }
}

func (w *heldBack) asked(path string, list bool) error {
	if strings.Contains(path, w.first) {
		w.once.Do(func() { close(w.seen) })
	}
	if !w.hold(path, list) {
		return nil
	}
	// The reads that may come first run on goroutines already started:
	// yielding to them is enough, and needs no clock.
	for range 100000 {
		select {
		case <-w.seen:
			return nil
		default:
			runtime.Gosched()
		}
	}
	return fmt.Errorf("%s was read before anything asked for %s", path, w.first)
}

func (w *heldBack) Get(path string) ([]byte, error) {
	if err := w.asked(path, false); err != nil {
		return nil, err
	}
	return w.GitHub.Get(path)
}

func (w *heldBack) List(path string) ([]byte, error) {
	if err := w.asked(path, true); err != nil {
		return nil, err
	}
	return w.GitHub.List(path)
}

// A page of the open issue list starts the reads its issues need as it
// arrives, while the next page is read.
func TestAPagesReadsStartBeforeTheNextPage(t *testing.T) {
	t.Parallel()
	var list []string
	for n := 1; n <= ListPage+1; n++ {
		list = append(list, fmt.Sprintf(`{"id":%d,"number":%d,"title":"t%d","state":"open"}`, 100+n, n, n))
	}
	gh := recorded(t, map[string]string{listPath: "[" + strings.Join(list, ",") + "]", refsPath: `[]`})
	// #1 is linked as blocked by #2 now: its links are read, as page 1 has it.
	if _, err := gh.Send("POST", "repos/o/r/issues/1/dependencies/blocked_by", github.Int("issue_id", 102)); err != nil {
		t.Fatal(err)
	}
	s := Source{Proc: machine, Repo: repo, GitHub: waitFor(gh, func(path string, list bool) bool {
		// The second page, or the whole list read at once, which holds it.
		return strings.HasPrefix(path, "repos/o/r/issues?labels=se&state=open&") && (list || strings.HasSuffix(path, "&page=2"))
	}, links(1)), Clock: atNow()}
	all, err := s.Survey()
	if err != nil {
		t.Fatal(err)
	}
	if len(all) != ListPage+1 || all[0].Why != "blocked by #2" || all[ListPage].Why != "" {
		t.Fatalf("%d issues, #1 %q", len(all), all[0].Why)
	}
}

// A settled summary that counts no open blocker stands for the links, though
// it counts a closed one; se fleet check, which judges closed blockers, reads
// them still.
func TestASettledSummaryWithNoOpenBlockerStandsForItsLinks(t *testing.T) {
	t.Parallel()
	clk := atNow()
	gh := recordedAt(t, clk, map[string]string{
		listPath: `[{"id":105,"number":5,"title":"t5","state":"open","updated_at":"2026-10-13T09:00:00Z"},` +
			`{"id":106,"number":6,"title":"t6","state":"open","updated_at":"2026-10-13T09:00:00Z"}]`,
		refsPath: `[]`,
	})
	if _, err := gh.Send("POST", "repos/o/r/issues/5/dependencies/blocked_by", github.Int("issue_id", 106)); err != nil {
		t.Fatal(err)
	}
	if _, err := gh.Send("PATCH", "repos/o/r/issues/6", github.F("state", "closed"), github.F("state_reason", "not_planned")); err != nil {
		t.Fatal(err)
	}
	clk.Advance(Settle + github.SummaryLag)
	c := &counting{GitHub: gh}
	s := Source{Proc: machine, Repo: repo, GitHub: c, Clock: clk}
	all, err := s.Survey()
	if err != nil || len(all) != 1 || all[0].Number != 5 || all[0].Why != "" {
		t.Fatalf("%+v %v", all, err)
	}
	if got := c.read(); len(got) != 0 {
		t.Fatalf("the links of an issue with no open blocker were read: %v", got)
	}
	found, err := s.Check()
	if err != nil {
		t.Fatal(err)
	}
	if got := c.read(); !slices.Equal(got, []string{links(5)}) {
		t.Fatalf("fleet check read the links of %v", got)
	}
	if !slices.ContainsFunc(found, func(f Finding) bool { return f.Kind == ImpossibleBlock && f.Issue == 5 }) {
		t.Fatalf("fleet check found %+v", found)
	}
}

// listing is GitHub that lists every path read through it.
type listing struct {
	github.GitHub
	paths chan string
}

func (l listing) Get(path string) ([]byte, error)  { l.paths <- path; return l.GitHub.Get(path) }
func (l listing) List(path string) ([]byte, error) { l.paths <- path; return l.GitHub.List(path) }

// The cadence reads the counted issues updated last beside the last closed
// run, and reads its whole window after it only where that page does not
// reach back to the run.
func TestTheCadenceCountsBesideTheLastRun(t *testing.T) {
	t.Parallel()
	// Retro #20 closed on October 1st; of the se issues closed, more than the
	// pages read beside it hold, after is how many closed, and were last
	// updated, after it.
	all := recentPage*recentPages + 10
	repoOf := func(after int) map[string]string {
		var closed []string
		for k := 0; k < all; k++ {
			at := "2026-09-20T12:00:00Z"
			if k < after {
				at = fmt.Sprintf("2026-10-%02dT12:00:00Z", 2+k%9)
			}
			closed = append(closed, fmt.Sprintf(`{"number":%d,"state":"closed","closed_at":%q,"updated_at":%q}`, 100+k, at, at))
		}
		return map[string]string{
			closedRetrosPath: `[{"number":20,"state":"closed","closed_at":"2026-10-01T00:00:00Z"}]`,
			openRetrosPath:   `[]`,
			closedSincePath:  "[" + strings.Join(closed, ",") + "]",
		}
	}
	for _, tc := range []struct {
		after  int
		window bool
	}{{5, false}, {all - 5, true}} {
		paths := make(chan string, 1000)
		gh := waitFor(listing{GitHub: recorded(t, repoOf(tc.after)), paths: paths}, holds(closedRetrosPath), "&sort=updated")
		c, err := Source{Repo: repo, GitHub: gh, Clock: atNow()}.Cadence()
		if err != nil || c.Closed != tc.after || c.Previous != 20 {
			t.Fatalf("%d after: %+v %v", tc.after, c, err)
		}
		close(paths)
		read := false
		for p := range paths {
			read = read || p == closedSincePath
		}
		if read != tc.window {
			t.Fatalf("%d after: the window read: %v", tc.after, read)
		}
	}
}
