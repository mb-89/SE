package shape_test

import (
	"embed"
	"fmt"
	"io/fs"
	"path"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/shape"
)

// fixture is a checkout holding one program, a library with every fact in
// it, its fake and test, a test helper, and a script.
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

// checkout seeds a fake disk with the fixture at /co, and a fake machine
// whose deadcode and git answer for it; withDeadcode false leaves deadcode off.
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
		case "ls-files":
			_, _ = fmt.Fprint(c.Stdout, "src/cmd/app/main.go\x00src/internal/lib/lib.go\x00src/scripts/once.sh\x00")
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
	in, err := shape.Read(d, m, "/co")
	if err != nil {
		t.Fatal(err)
	}
	in.Commands = []shape.Surface{{Name: "issue land", Flags: []string{"answers"}}, {Name: "fleet prune", Flags: []string{"apply"}}}
	in.Answers = []string{"Ran se issue land once."}
	in.ReadBy = day(6)
	f := shape.Find(in)
	draft := f.Markdown()
	for fact, want := range map[string]string{
		"production-unreachable": "- src/internal/lib/lib.go:37: OnlyTests\n- src/internal/lib/lib.go:40: Old\n\n",
		"a duplicate":            "- Copy (src/internal/lib/lib.go:43) and Again (src/internal/lib/lib.go:55), 100% alike",
		"a near-duplicate":       "- Near (src/internal/lib/lib.go:67) and Far (src/internal/lib/lib.go:80), 100% alike",
		"the package sizes":      "| src/internal/lib | 79 | 12 | 0.15 | 72% |",
		"a module's size":        "| src/internal/libtest | 4 | 0 | 0.00 | 4% |",
		"the totals":             "All: 109 lines of code, 12 of tests, a test ratio of 0.11.",
		"a one-user library":     "- src/internal/lib: imported only by src/cmd/app",
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
	// fake, a command a landing answer names, or a file git no longer tracks.
	unreachable, _, _ := strings.Cut(draft, "### Duplicates")
	for _, not := range []string{"FakeClock", "Seven"} {
		if strings.Contains(unreachable, not) {
			t.Errorf("production-unreachable shows %q:\n%s", not, unreachable)
		}
	}
	for _, not := range []string{"Clock, implemented", "`se issue land`,", "gone.txt"} {
		if strings.Contains(draft, not) {
			t.Errorf("the draft shows %q:\n%s", not, draft)
		}
	}
}

func TestTheFactsSayWhenDeadcodeIsMissing(t *testing.T) {
	t.Parallel()
	d, m := checkout(t, false)
	in, err := shape.Read(d, m, "/co")
	if err != nil {
		t.Fatal(err)
	}
	if draft := shape.Find(in).Markdown(); !strings.Contains(draft, "Not found: deadcode is not installed: sh tests/tools.sh install installs it.") {
		t.Fatal(draft)
	}
}
