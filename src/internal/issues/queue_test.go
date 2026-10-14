// Internal test package: it uses the package's recorded-gh fakes.
package issues

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"
)

// queueRepo records o/r with an open queue of ten flat issues, #1 to #10,
// four of them claimed, and a chain of four, #11 before #12 before #13
// before #14; and, in the pace window, four issues merged with claim-to-merge
// times of 60, 60, 120 and 240 minutes, and one closed without a PR.
func queueRepo(t *testing.T) map[string]string {
	t.Helper()
	var open []string
	for n := 1; n <= 14; n++ {
		open = append(open, node(n, 0))
	}
	a := map[string]string{
		listPath:        list(open...),
		refsPath:        `[{"ref":"refs/heads/issue-1"},{"ref":"refs/heads/issue-2"},{"ref":"refs/heads/issue-3"},{"ref":"refs/heads/issue-4"}]`,
		blockedPath(12): subs(11),
		blockedPath(13): subs(12),
		blockedPath(14): subs(13),
	}
	pushedAt(a, fresh, 1, 2, 3, 4)
	var closed, pulls []string
	for k, took := range []int{60, 60, 120, 240} {
		n := 101 + k
		merged := now.Add(-time.Duration(24*(k+1)) * time.Hour)
		claimed := merged.Add(-time.Duration(took) * time.Minute)
		closed = append(closed, closedJSON(n, "completed", merged.Format(time.RFC3339), NewMark, ""))
		pulls = append(pulls, fmt.Sprintf(`{"number":%d,"title":"p","body":"Fixes #%d","merged_at":%q,"merge_commit_sha":"m%d","head":{"sha":"h%d"}}`, 200+k, n, merged.Format(time.RFC3339), n, n))
		a[fmt.Sprintf("repos/o/r/issues/%d/comments?per_page=100", n)] = jsonComments(landing(t, n, map[string]string{"done": "d"}, claimed))
	}
	// Closed without a PR, and a merge before the window: neither counts.
	closed = append(closed, closedJSON(105, "not_planned", now.Add(-time.Hour).Format(time.RFC3339), NewMark, ""))
	pulls = append(pulls, `{"number":199,"title":"old","body":"Fixes #99","merged_at":"2026-09-01T00:00:00Z","merge_commit_sha":"m99","head":{"sha":"h99"}}`)
	a["repos/o/r/issues?labels=se&state=closed&per_page=100&since=2026-10-06T12:00:00Z"] = "[" + strings.Join(closed, ",") + "]"
	a["repos/o/r/pulls?state=closed&base=main&per_page=100"] = "[" + strings.Join(pulls, ",") + "]"
	return a
}

func TestTheQueueEstimateFollowsThePaceAndNamesTheChain(t *testing.T) {
	t.Parallel()
	gh := recorded(t, queueRepo(t))
	q, nodes, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Queue(0, PaceWindow)
	if err != nil {
		t.Fatal(err)
	}
	p := q.Pace
	if p.Merged != 4 || p.Measured != 4 || p.P50 != 120 || p.P90 != 240 || p.PerHour != 0.02 {
		t.Fatalf("pace %+v", p)
	}
	if q.Open != 14 || !reflect.DeepEqual(q.InFlight, []int{1, 2, 3, 4}) || q.Parallel != 4 {
		t.Fatalf("%+v", q)
	}
	if !reflect.DeepEqual(q.Critical, []int{11, 12, 13, 14}) {
		t.Fatalf("critical path %v", q.Critical)
	}
	// The chain sets both: 4 × 2h at p50, 4 × 4h at p90, where the 14
	// spread over 4 at once take 7h and 14h.
	if q.P50Hours != 8 || q.P90Hours != 16 || !q.P50At.Equal(now.Add(8*time.Hour)) || !q.P90At.Equal(now.Add(16*time.Hour)) {
		t.Fatalf("%+v", q)
	}
	if len(nodes) != 14 || nodes[0].Why != "claimed by issue-1" || nodes[4].Why != "ready" || nodes[13].Why != "blocked by #13" {
		t.Fatalf("%+v", nodes)
	}
	text := q.Text()
	for _, part := range []string{
		"Estimate: 14 open, 4 in flight; the last closes in 8h (p50) to 16h (p90), by 2026-10-13 20:00Z to 2026-10-14 04:00Z.",
		"In flight: #1, #2, #3, #4.",
		"4 merged, 0.02 an hour; claim to merge 2h (p50) to 4h (p90), of 4 measured.",
		"Parallel: 4 at once.",
		"At the window's pace, idle hours and all, the 14 take 24.5d.",
		"Critical path, 4 in a row: #11 → #12 → #13 → #14.",
	} {
		if !strings.Contains(text, part) {
			t.Errorf("no %q in\n%s", part, text)
		}
	}
}

func TestAStuckClaimDoesNotCountAsRunning(t *testing.T) {
	t.Parallel()
	a := queueRepo(t)
	a[activity(4)] = pushed(stale)
	q, _, err := Source{Proc: machine, Repo: repo, GitHub: recorded(t, a), Clock: atNow()}.Queue(0, PaceWindow)
	if err != nil {
		t.Fatal(err)
	}
	// Three run: the 14 spread over them take 14 × 2h / 3, past the chain.
	if !reflect.DeepEqual(q.Stuck, []int{4}) || q.Parallel != 3 || q.P50Hours != 9.33 || !strings.Contains(q.Text(), "stuck, not counted as running: #4") {
		t.Fatalf("%+v", q)
	}
}

func TestWideWorkOutlastsTheChainWithFewRunning(t *testing.T) {
	t.Parallel()
	a := queueRepo(t)
	a[refsPath] = `[]`
	gh := recorded(t, a)
	q, _, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}.Queue(0, PaceWindow)
	if err != nil {
		t.Fatal(err)
	}
	// None in flight and a slow pace: one at a time, 14 × 2h and 14 × 4h.
	if q.Parallel != 1 || q.P50Hours != 28 || q.P90Hours != 56 || len(q.Critical) != 4 {
		t.Fatalf("%+v", q)
	}
}

func TestATreesChainCountsItsParentsBlockersAndItsReview(t *testing.T) {
	t.Parallel()
	// #20, a review gate, holds #21 and #22; #22 is blocked by #21, and #20
	// by #23 outside it, so #23, #21, #22, then #20's review run in a row.
	gh := recorded(t, map[string]string{
		listPath:        list(node(20, 2, "se-review"), node(21, 0), node(22, 0), node(23, 0), node(24, 0)),
		refsPath:        `[]`,
		subsPath(20):    subs(21, 22),
		blockedPath(20): subs(23),
		blockedPath(22): subs(21),
	})
	s := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: atNow()}
	q, _, err := s.Queue(0, PaceWindow)
	if err != nil {
		t.Fatal(err)
	}
	if q.Open != 5 || !reflect.DeepEqual(q.Critical, []int{23, 21, 22, 20}) || !strings.HasPrefix(q.Why, "no se issue merged") || q.P50At != nil {
		t.Fatalf("%+v", q)
	}
	// Inside #20's tree, #23 is outside: the chain starts at #21.
	q, nodes, err := s.Queue(20, PaceWindow)
	if err != nil {
		t.Fatal(err)
	}
	if q.Open != 3 || !reflect.DeepEqual(q.Critical, []int{21, 22, 20}) || len(nodes) != 3 || nodes[1].Depth != 1 {
		t.Fatalf("%+v %+v", q, nodes)
	}
}
