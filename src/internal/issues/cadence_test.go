// Internal test package: it reuses the recorded answers of issues_test.go.
package issues

import (
	"fmt"
	"strings"
	"testing"
)

const (
	closedRetrosPath = "repos/o/r/issues?labels=se-retro&state=closed&per_page=100"
	openRetrosPath   = "repos/o/r/issues?labels=se-retro&state=open&per_page=100"
	// retro #20 closed on October 1st; the closed list is asked since then.
	closedSincePath = "repos/o/r/issues?labels=se&state=closed&per_page=100&since=2026-10-01T00:00:00Z"
)

// cadenceRepo records o/r with retro #20 closed and n se issues closed after
// it, #100 on; openRetro, where it is not 0, is an open retro.
func cadenceRepo(n, openRetro int) map[string]string {
	var closed []string
	for k := 0; k < n; k++ {
		closed = append(closed, fmt.Sprintf(`{"number":%d,"state":"closed","closed_at":"2026-10-0%dT12:00:00Z"}`, 100+k, 2+k%7))
	}
	// Before the window, touched inside it: the list holds it, the count does not.
	closed = append(closed, `{"number":19,"state":"closed","closed_at":"2026-09-29T00:00:00Z"}`)
	// A retro closed in the window, and a pull request: neither counts.
	closed = append(closed, `{"number":21,"state":"closed","closed_at":"2026-10-03T00:00:00Z","labels":[{"name":"se"},{"name":"se-retro"}]}`,
		`{"number":22,"state":"closed","closed_at":"2026-10-03T00:00:00Z","pull_request":{}}`)
	open := `[]`
	if openRetro != 0 {
		open = fmt.Sprintf(`[{"number":%d,"state":"open","labels":[{"name":"se"},{"name":"se-retro"}]}]`, openRetro)
	}
	return unblocked(map[string]string{
		closedRetrosPath:   `[{"number":10,"state":"closed","closed_at":"2026-09-01T00:00:00Z"},{"number":20,"state":"closed","closed_at":"2026-10-01T00:00:00Z"}]`,
		openRetrosPath:     open,
		closedSincePath:    "[" + strings.Join(closed, ",") + "]",
		listPath:           `[` + open5 + `]`,
		refsPath:           `[]`,
		"repos/o/r/issues": `{"id":130,"number":30,"title":"SE retro 2026-10-13","html_url":"u30"}`,
	}, 5)
}

var open5 = `{"number":5,"title":"t5","body":"work","state":"open","html_url":"u5"}`

// writing records gh's answers and every write it is asked for.
func writing(t *testing.T, answers map[string]string) (GH, *[][]string) {
	t.Helper()
	read := recorded(t, answers)
	var w [][]string
	return func(args ...string) ([]byte, error) {
		if len(args) > 1 && args[1] == "-X" {
			w = append(w, args)
		}
		return read(args...)
	}, &w
}

func TestNineClosedStartNoRetro(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	gh, w := writing(t, cadenceRepo(9, 0))
	s := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}
	took, ok, c, err := s.TakeRetro(a)
	if err != nil || ok || c.Closed != 9 || c.Previous != 20 || c.Due() || len(*w) != 0 {
		t.Fatalf("took %+v %v, %+v %v, writes %q", took, ok, c, err, *w)
	}
	if got := c.Line(); got != "9 se issues closed since the retro #20 closed; a retro is due at 10." {
		t.Fatalf("%q", got)
	}
	if took, ok, err := s.Take(a, 0); err != nil || !ok || took.Number != 5 {
		t.Fatalf("took %+v %v %v", took, ok, err)
	}
}

func TestTenClosedStartAnUnattendedRetroAndTakeItFirst(t *testing.T) {
	t.Parallel()
	_, a, _ := boxes(t)
	gh, w := writing(t, cadenceRepo(10, 0))
	s := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}
	took, ok, c, err := s.TakeRetro(a)
	if err != nil || !ok || took.Number != 30 || !took.Retro || c.Closed != 10 {
		t.Fatalf("took %+v %v, %+v %v", took, ok, c, err)
	}
	if len(*w) != 1 || !strings.Contains(strings.Join((*w)[0], " "), unattendedMark) || !strings.Contains(strings.Join((*w)[0], " "), "labels[]=se-retro") {
		t.Fatalf("writes %q", *w)
	}
	if got := run(t, a, "rev-parse", "--abbrev-ref", "HEAD"); got != "issue-30" {
		t.Fatalf("a is on %s", got)
	}
}

func TestAnOpenRetroBlocksASecond(t *testing.T) {
	t.Parallel()
	for _, n := range []int{10, 25} {
		gh, w := writing(t, cadenceRepo(n, 31))
		took, ok, c, err := Source{Proc: machine, Repo: repo, GH: gh, Clock: atNow()}.TakeRetro(t.TempDir())
		if err != nil || ok || c.Open != 31 || c.Due() || len(*w) != 0 {
			t.Fatalf("%d closed: took %+v %v, %+v %v, writes %q", n, took, ok, c, err, *w)
		}
		if got := c.Line(); !strings.HasSuffix(got, "; the retro #31 is open.") {
			t.Fatalf("%q", got)
		}
	}
}

func TestRetroIssuesAreNotCounted(t *testing.T) {
	t.Parallel()
	// cadenceRepo(9, …) holds a closed retro and a pull request inside the
	// window, besides the nine: counted, they would make the cadence due.
	c, err := Source{Proc: machine, Repo: repo, GH: recorded(t, cadenceRepo(9, 0)), Clock: atNow()}.Cadence()
	if err != nil || c.Closed != 9 {
		t.Fatalf("%+v %v", c, err)
	}
}

func TestTheFirstCadenceCountsTheWholeHistory(t *testing.T) {
	t.Parallel()
	c, err := Source{Proc: machine, Repo: repo, GH: recorded(t, map[string]string{
		closedRetrosPath: `[]`,
		openRetrosPath:   `[]`,
		"repos/o/r/issues?labels=se&state=closed&per_page=100": `[{"number":1,"state":"closed","closed_at":"2026-01-01T00:00:00Z"}]`,
	}), Clock: atNow()}.Cadence()
	if err != nil || c.Closed != 1 || c.Previous != 0 {
		t.Fatalf("%+v %v", c, err)
	}
	if got := c.Line(); got != "1 se issue closed and no retro has closed yet; a retro is due at 10." {
		t.Fatalf("%q", got)
	}
}
