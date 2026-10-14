package battery_test

import (
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/disk"
)

const overrunClasses = `classes:
  instant: {ms: 1000, hard: false}
  local: {ms: 10000, hard: true}
  daemon: {ms: 0, hard: false}
command_classes:
  help: instant
  rules: local
  serve: daemon
hook_classes:
  classic.Stop: local
  '*': instant
`

// put writes text to the file at path in the workspace dir on d, making its folder.
func put(t *testing.T, d disk.Disk, dir, path, text string) {
	t.Helper()
	at := filepath.Join(dir, filepath.FromSlash(path))
	if err := d.MkdirAll(filepath.Dir(at)); err != nil {
		t.Fatal(err)
	}
	if err := d.WriteFile(at, []byte(text)); err != nil {
		t.Fatal(err)
	}
}

func TestOverrunsNameEachCommandAndHookOverItsClassInTheSpan(t *testing.T) {
	t.Parallel()
	d, dir := workspace(t, "", overrunClasses)
	put(t, d, dir, battery.CallsFile, strings.Join([]string{
		`{"at":"2026-10-01T00:00:00Z","name":"help","ms":5000}`, // before the span
		`{"at":"2026-10-05T00:00:00Z","name":"help","ms":40}`,
		`{"at":"2026-10-05T01:00:00Z","name":"help","ms":1500}`,
		`{"at":"2026-10-05T02:00:00Z","name":"help","ms":3000}`,
		`{"at":"2026-10-05T03:00:00Z","name":"rules","ms":9000}`, // within its class
		`{"at":"2026-10-05T04:00:00Z","name":"serve","ms":9e6}`,  // a class of 0ms bounds nothing
		`{"at":"2026-10-05T05:00:00Z","name":"new","ms":9e6}`,    // in no class
		`not a call`,
	}, "\n")+"\n")
	put(t, d, dir, ".se/.runtime/logs/s1.jsonl", strings.Join([]string{
		`{"at":"2026-10-05T00:00:00.000Z","event":"se.hook","e":{"hook":"classic.Stop","ms":12500}}`,
		`{"at":"2026-10-05T00:00:01.000Z","event":"se.hook","e":{"hook":"*","ms":3}}`,
		`{"at":"2026-10-05T00:00:02.000Z","event":"se.call","e":{"words":["help"],"ms":90000}}`,
		`{"at":"2026-10-20T00:00:00.000Z","event":"se.hook","e":{"hook":"*","ms":5000}}`, // after the span
	}, "\n")+"\n")
	put(t, d, dir, ".se/.runtime/logs/s2.jsonl", `{"at":"2026-10-06T00:00:00.000Z","event":"se.hook","e":{"hook":"*","ms":1200}}`+"\n")
	put(t, d, dir, ".se/.runtime/logs/daemon.log", "not a session log\n")

	from, to := time.Date(2026, 10, 2, 0, 0, 0, 0, time.UTC), time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC)
	got, err := battery.Overruns(d, dir, from, to)
	if err != nil {
		t.Fatal(err)
	}
	want := []battery.Overrun{
		{Kind: "command", Name: "help", Class: "instant", Budget: 1000, Calls: 3, Over: 2, Worst: 3000, Excess: 2500},
		{Kind: "hook", Name: "*", Class: "instant", Budget: 1000, Calls: 2, Over: 1, Worst: 1200, Excess: 200},
		{Kind: "hook", Name: "classic.Stop", Class: "local", Budget: 10000, Hard: true, Calls: 1, Over: 1, Worst: 12500, Excess: 2500},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v\nwant %+v", got, want)
	}
}

func TestAWorkspaceThatRecordedNothingHasNoOverruns(t *testing.T) {
	t.Parallel()
	d, dir := workspace(t, "", overrunClasses)
	end := time.Date(2026, 10, 14, 0, 0, 0, 0, time.UTC)
	got, err := battery.Overruns(d, dir, time.Time{}, end)
	if err != nil || len(got) != 0 {
		t.Fatalf("%+v %v", got, err)
	}
	bare := filepath.FromSlash("/bare")
	put(t, d, bare, battery.CallsFile, `{"at":"2026-10-05T00:00:00Z","name":"help","ms":5000}`+"\n")
	if got, err := battery.Overruns(d, bare, time.Time{}, end); err != nil || len(got) != 0 {
		t.Fatalf("a workspace without budgets: %+v %v", got, err)
	}
}
