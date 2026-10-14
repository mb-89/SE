package shape_test

import (
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"path"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/shape"
)

// fixture is a checkout holding one program, a library with every fact in
// it, its fake and test, a library only that library imports, a test helper,
// and a script.
//
//go:embed testdata/checkout
var fixture embed.FS

// unreachable is what deadcode says of the fixture without -test.
const unreachable = `internal/lib/lib.go:37:6: unreachable func: OnlyTests
internal/lib/lib.go:40:6: unreachable func: Old
internal/lib/fake.go:7:19: unreachable func: FakeClock.Now
internal/libtest/libtest.go:5:6: unreachable func: Seven`

// day is a day of the fixture's history.
func day(d int) time.Time { return time.Date(2026, 10, d, 12, 0, 0, 0, time.UTC) }

// logs is the session log folder in a checkout.
const logs = ".se/logs"

// checkout seeds a fake disk with the fixture at /co, a worktree of /main,
// and a fake machine whose deadcode and git answer for it; withDeadcode false
// leaves deadcode off.
func checkout(t *testing.T, withDeadcode bool) (*disk.Fake, *proc.Fake) {
	t.Helper()
	d := disk.NewFake()
	err := fs.WalkDir(fixture, "testdata/checkout", func(p string, e fs.DirEntry, err error) error {
		if err != nil || e.IsDir() {
			return err
		}
		data, err := fixture.ReadFile(p)
		if err != nil {
			return err
		}
		to := path.Join("/co", strings.TrimPrefix(p, "testdata/checkout/"))
		if err := d.MkdirAll(path.Dir(to)); err != nil {
			return err
		}
		return d.WriteFile(to, data)
	})
	if err == nil {
		err = d.WriteFile("/co/src/go.mod", []byte("module example.com/fix\n\ngo 1.24\n"))
	}
	if err != nil {
		t.Fatal(err)
	}
	m := proc.NewFake()
	if withDeadcode {
		m.Install("deadcode", func(c proc.Cmd) int {
			if c.Dir != "/co/src" {
				return 2
			}
			fmt.Fprintln(c.Stdout, unreachable)
			return 0
		})
	}
	record := func(at time.Time, subject string, files ...string) string {
		return fmt.Sprintf("\x1e%s\x1f%d\x1f%s\n\n%s\n", strings.Repeat("a", 40), at.Unix(), subject, strings.Join(files, "\n"))
	}
	m.Install("git", func(c proc.Cmd) int {
		switch c.Args[0] {
		case "rev-parse":
			fmt.Fprintln(c.Stdout, "/main/.git")
		case "ls-files":
			fmt.Fprintln(c.Stdout, "src/cmd/app/main.go\nsrc/internal/lib/lib.go\nsrc/scripts/once.sh")
		case "log":
			_, _ = fmt.Fprint(c.Stdout,
				record(day(9), "Touch the program and the library", "src/cmd/app/main.go", "src/internal/lib/lib.go", "src/internal/lib/fake.go")+
					record(day(5), "Add the script", "src/scripts/once.sh")+
					record(day(2), "Start", "src/internal/lib/lib.go", "gone.txt"))
		default:
			return 1
		}
		return 0
	})
	return d, m
}

func TestTheFixtureShowsEveryFact(t *testing.T) {
	t.Parallel()
	d, m := checkout(t, true)
	in, err := shape.Read(d, m, "/co", logs)
	if err != nil {
		t.Fatal(err)
	}
	in.Commands = []shape.Surface{{Name: "issue land", Flags: []string{"answers"}}, {Name: "fleet prune", Flags: []string{"apply"}}}
	in.Ran = []shape.Ran{{Line: "se issue land"}}
	in.ReadBy = day(6)
	f := shape.Find(in)
	draft := f.Markdown()
	for fact, want := range map[string]string{
		"production-unreachable": "- src/internal/lib/lib.go:37: OnlyTests\n- src/internal/lib/lib.go:40: Old\n\n",
		"a duplicate":            "- Copy (src/internal/lib/lib.go:43) and Again (src/internal/lib/lib.go:55), 100% alike",
		"a near-duplicate":       "- Near (src/internal/lib/lib.go:67) and Far (src/internal/lib/lib.go:80), 100% alike",
		"the package sizes":      "| src/internal/lib | 83 | 12 | 0.14 | 71% |",
		"a module's size":        "| src/internal/libtest | 4 | 0 | 0.00 | 3% |",
		"the totals":             "All: 117 lines of code, 12 of tests, a test ratio of 0.10.",
		"a one-user library":     "- src/internal/words: imported only by src/internal/lib",
		"a one-entry registry":   "- src/internal/lib/lib.go:31: Register has 1 entry",
		"a one-user interface":   "- src/internal/lib/lib.go:7: Store, implemented only by lib.Disk",
		"the unused surfaces":    "`se issue land --answers`, `se fleet prune`.",
		"a legacy state":         "- src/internal/lib/lib.go:39: Old is kept for issues from before the move, whose last one has closed.",
		"a script":               "- src/scripts/once.sh (read by the last retro, added 2026-10-05): a one-off that ran se issue land for every branch; it names se issue land",
		"the untouched longest":  "- src/scripts/once.sh, last changed 2026-10-05\n- src/cmd/app/main.go, last changed 2026-10-09",
		"a long function":        "- 11 lines: Near (src/internal/lib/lib.go:67)",
		"the longest file":       "- 90 lines: lib.go (src/internal/lib/lib.go)",
		"a long parameter list":  "- 6 parameters: wide (src/cmd/app/main.go:31)",
		"a switch on a kind":     "- 3 arms: switch on k (src/cmd/app/main.go:19)",
		"files per change":       "Over the last 3 changes on main: a median of 2 files, at most 3. The widest:\n\n- 3 files: Touch the program and the library",
	} {
		if !strings.Contains(draft, want) {
			t.Errorf("the draft does not show %s, %q:\n%s", fact, want, draft)
		}
	}
	// The fake and the test helper are no candidates, nor an interface with a
	// fake, a library only the program imports, a command that ran, or a file
	// git no longer tracks.
	unreachable, _, _ := strings.Cut(draft, "### Duplicates")
	for _, not := range []string{"FakeClock", "Seven"} {
		if strings.Contains(unreachable, not) {
			t.Errorf("production-unreachable shows %q:\n%s", not, unreachable)
		}
	}
	for _, not := range []string{"Clock, implemented", "`se issue land`,", "gone.txt", "src/internal/lib: imported only"} {
		if strings.Contains(draft, not) {
			t.Errorf("the draft shows %q:\n%s", not, draft)
		}
	}
}

// row is a session log row of the event at t.
func row(t *testing.T, at time.Time, event string, e any) string {
	t.Helper()
	data, err := json.Marshal(map[string]any{"at": at.Format(time.RFC3339Nano), "event": event, "e": e})
	if err != nil {
		t.Fatal(err)
	}
	return string(data) + "\n"
}

func TestUnusedSurfacesCountTheCommandLinesThatRan(t *testing.T) {
	t.Parallel()
	d, m := checkout(t, true)
	bash := func(command string) map[string]any {
		return map[string]any{"tool_name": "Bash", "tool_input": map[string]any{"command": command}}
	}
	for path, rows := range map[string]string{
		// The worktree's own log: a Bash call landing, and one from before
		// the window, which does not count.
		"/co/.se/logs/a.jsonl": row(t, day(8), "tool.before", bash("/home/u/SE/src/plugin/bin/se issue new --title T --body-file F --blocked-by none && ./src/plugin/bin/se issue land --workspace /co --answers a.yaml")) +
			row(t, day(1), "tool.before", bash("se fleet prune --apply")) +
			"no row\n",
		// The main checkout's: a call through /se.
		"/main/.se/logs/b.jsonl":    row(t, day(8), "se.call", map[string]any{"words": []string{"overhaul", "new"}, "ms": 3}),
		"/main/.se/logs/daemon.log": "se fleet prune --apply\n",
	} {
		if err := d.MkdirAll(path[:strings.LastIndex(path, "/")]); err != nil {
			t.Fatal(err)
		}
		if err := d.WriteFile(path, []byte(rows)); err != nil {
			t.Fatal(err)
		}
	}
	in, err := shape.Read(d, m, "/co", logs)
	if err != nil {
		t.Fatal(err)
	}
	in.Commands = []shape.Surface{
		{Name: "issue land", Flags: []string{"answers", "json"}},
		{Name: "issue new", Flags: []string{"title", "body-file", "blocked-by", "parent"}},
		{Name: "issue pull", Flags: []string{"take", "worktree"}},
		{Name: "fleet prune", Flags: []string{"apply"}},
		{Name: "overhaul new", Flags: []string{"unattended"}},
		{Name: "retro report", Flags: []string{"draft"}},
	}
	// What the comments se wrote stand for: a claim.
	in.Ran = append(in.Ran, shape.Ran{Line: "se issue pull --take"})
	in.Since = day(3)
	f := shape.Find(in)
	want := []string{"se issue land --json", "se issue new --parent", "se issue pull --worktree", "se fleet prune", "se overhaul new --unattended", "se retro report"}
	if !slices.Equal(f.Unused, want) {
		t.Fatalf("unused %q, want %q", f.Unused, want)
	}
	if draft := f.Markdown(); !strings.Contains(draft, "`se issue land --json`, `se issue new --parent`, ") {
		t.Fatal(draft)
	}
}

func TestUnusedSurfacesAreDroppedWhereNothingSaysWhatRan(t *testing.T) {
	t.Parallel()
	d, m := checkout(t, true)
	in, err := shape.Read(d, m, "/co", logs)
	if err != nil {
		t.Fatal(err)
	}
	in.Commands = []shape.Surface{{Name: "issue land", Flags: []string{"answers"}}}
	in.Ran = []shape.Ran{{Line: "go test ./..."}}
	f := shape.Find(in)
	if len(f.Unused) != 0 || f.Counted != 0 {
		t.Fatalf("%+v", f.Unused)
	}
	if draft := f.Markdown(); !strings.Contains(draft, "Dropped: no session log here and no comment se wrote names an se command that ran in the whole history") || strings.Contains(draft, "`se issue land") {
		t.Fatal(draft)
	}
}

func TestAMissingDeadcodeIsInstalledAtItsPin(t *testing.T) {
	t.Parallel()
	d, m := checkout(t, false)
	m.Install("sh", func(c proc.Cmd) int {
		if c.Dir != "/co" || len(c.Args) != 2 || !strings.HasPrefix(c.Args[1], "sh tests/tools.sh install ") || !strings.HasSuffix(c.Args[1], "deadcode ./...") {
			return 2
		}
		fmt.Fprintln(c.Stdout, unreachable)
		return 0
	})
	in, err := shape.Read(d, m, "/co", logs)
	if err != nil {
		t.Fatal(err)
	}
	if draft := shape.Find(in).Markdown(); !strings.Contains(draft, "- src/internal/lib/lib.go:37: OnlyTests\n") {
		t.Fatal(draft)
	}
}

func TestTheReadRefusesADeadcodeItCannotInstall(t *testing.T) {
	t.Parallel()
	d, m := checkout(t, false)
	m.Install("sh", func(c proc.Cmd) int {
		fmt.Fprintln(c.Stderr, "tools: no release for the machine z80")
		return 1
	})
	_, err := shape.Read(d, m, "/co", logs)
	if !errors.Is(err, shape.ErrDeadcode) || !strings.Contains(err.Error(), "deadcode") || !strings.Contains(err.Error(), "sh tests/tools.sh install") || !strings.Contains(err.Error(), "z80") {
		t.Fatalf("%v", err)
	}
}
