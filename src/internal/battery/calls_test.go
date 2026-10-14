package battery_test

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/disk"
)

const classes = `classes:
  instant: {ms: 1000, hard: false}
  daemon: {ms: 0, hard: false}
commands:
  help: instant
  serve: daemon
`

// recorded answers every call recorded in the workspace dir on d.
func recorded(t *testing.T, d disk.Disk, dir string) []battery.Call {
	t.Helper()
	data, err := d.ReadFile(filepath.Join(dir, battery.CallsFile))
	if err != nil {
		t.Fatal(err)
	}
	var out []battery.Call
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		var c battery.Call
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			t.Fatal(err)
		}
		out = append(out, c)
	}
	return out
}

func TestEachCallIsRecordedAgainstItsClass(t *testing.T) {
	t.Parallel()
	d, dir := workspace(t, "", classes)
	if err := d.MkdirAll(filepath.Join(dir, ".se", ".runtime")); err != nil {
		t.Fatal(err)
	}
	at := time.Date(2026, 10, 14, 9, 0, 0, 0, time.UTC)
	for _, c := range []battery.Call{{At: at, Name: "help", Ms: 40}, {At: at, Name: "help", Ms: 1500}, {At: at, Name: "serve", Ms: 9e6}, {At: at, Name: "new", Ms: 5}} {
		if _, err := battery.Record(d, dir, c); err != nil {
			t.Fatal(err)
		}
	}
	got := recorded(t, d, dir)
	if len(got) != 4 {
		t.Fatalf("recorded %d calls, want 4: %+v", len(got), got)
	}
	if got[0].Over || got[0].Budget == nil || got[0].Budget.Ms != 1000 {
		t.Errorf("a call within its class: %+v", got[0])
	}
	if !got[1].Over || got[1].Overrun() != "help took 1500ms, over its budget of 1000ms (spec/budgets.yaml)" {
		t.Errorf("a call over its class: %+v, %q", got[1], got[1].Overrun())
	}
	if got[2].Over {
		t.Errorf("a class of 0ms bounds a call: %+v", got[2])
	}
	if !got[3].Unbudgeted || got[3].Budget != nil {
		t.Errorf("a command in no class: %+v", got[3])
	}
}

func TestAWorkspaceWithoutARuntimeFolderRecordsNothing(t *testing.T) {
	t.Parallel()
	d, dir := disk.NewFake(), filepath.FromSlash("/elsewhere")
	if err := d.MkdirAll(dir); err != nil {
		t.Fatal(err)
	}
	if _, err := battery.Record(d, dir, battery.Call{Name: "help", Ms: 1}); err != nil {
		t.Fatal(err)
	}
	if there, _ := d.Exists(filepath.Join(dir, ".se")); there {
		t.Error("se made a runtime folder to time itself")
	}
}

func TestAWorkspaceWithoutBudgetsRecordsTheBareDuration(t *testing.T) {
	t.Parallel()
	d, dir := disk.NewFake(), filepath.FromSlash("/plain")
	if err := d.MkdirAll(filepath.Join(dir, ".se", ".runtime")); err != nil {
		t.Fatal(err)
	}
	if _, err := battery.Record(d, dir, battery.Call{Name: "help", Ms: 7}); err != nil {
		t.Fatal(err)
	}
	got := recorded(t, d, dir)
	if len(got) != 1 || got[0].Ms != 7 || got[0].Budget != nil || got[0].Unbudgeted {
		t.Errorf("recorded %+v", got)
	}
}
