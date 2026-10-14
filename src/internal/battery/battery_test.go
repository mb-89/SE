package battery_test

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/disk"
)

const budgets = `total: {ms: 1000, hard: false}
steps:
  go test: {ms: 500, hard: false}
  biome: {ms: 100, hard: false}
commands:
  interactive: {ms: 1000, requests: 3}
`

const events = `{"Action":"run","Package":"p","Test":"TestA"}
{"Action":"output","Package":"p","Test":"TestA","Output":"=== RUN   TestA\n"}
{"Action":"pass","Package":"p","Test":"TestA","Elapsed":0.25}
{"Action":"pass","Package":"p","Test":"TestB","Elapsed":1.5}
{"Action":"output","Package":"p","Test":"TestB/issue_pull","Output":"    b_test.go:9: battery-command: issue pull\t12\t3600\n"}
{"Action":"output","Package":"p","Test":"TestB/help","Output":"    b_test.go:9: battery-command: help\t0\t0\n"}
{"Action":"output","Package":"p","Test":"TestC","Output":"c.go:3: wrong\n"}
{"Action":"fail","Package":"p","Test":"TestC","Elapsed":0.01}
{"Action":"output","Package":"p","Output":"FAIL\tp\t1.8s\n"}
{"Action":"fail","Package":"p","Elapsed":1.8}
`

// workspace writes a battery run into a fresh workspace on a fake disk: the
// steps, go test's events and the budgets.
func workspace(t *testing.T, steps, budgetsYAML string) (disk.Disk, string) {
	t.Helper()
	d, dir := disk.NewFake(), filepath.FromSlash("/ws")
	at := filepath.Join(dir, battery.Dir)
	for path, text := range map[string]string{
		filepath.Join(at, battery.StepsFile):    steps,
		filepath.Join(at, battery.GoTestFile):   events,
		filepath.Join(dir, battery.BudgetsFile): budgetsYAML,
	} {
		if err := d.MkdirAll(filepath.Dir(path)); err != nil {
			t.Fatal(err)
		}
		if err := d.WriteFile(path, []byte(text)); err != nil {
			t.Fatal(err)
		}
	}
	return d, dir
}

func TestTheReportListsEveryDurationAndTheSlowestTests(t *testing.T) {
	t.Parallel()
	d, dir := workspace(t, "biome\t40\ngo test\t420\n", budgets)
	var summary bytes.Buffer
	p, err := battery.Report(d, dir, &summary)
	if err != nil {
		t.Fatal(err)
	}
	if p.TotalMs != 460 {
		t.Errorf("total = %d, want 460", p.TotalMs)
	}
	text := p.Text()
	for _, want := range []string{
		"battery: 460ms in total (soft budget 1000ms)",
		"battery: step biome 40ms (soft budget 100ms)",
		"battery: step go test 420ms (soft budget 500ms)",
		"battery:   1500ms p TestB",
		"battery:   250ms p TestA",
		"battery:   10ms p TestC",
		"battery: the 2 interactive commands (budget 1000ms and 3 requests each)",
		"battery:   0ms 0 requests se help",
		"battery:   3600ms 12 requests se issue pull",
	} {
		if !strings.Contains(text, want) {
			t.Errorf("the report lacks %q:\n%s", want, text)
		}
	}
	if strings.Index(text, "TestB") > strings.Index(text, "TestA") {
		t.Errorf("the slowest test is not first:\n%s", text)
	}
	if strings.Contains(text, "OVER BUDGET") {
		t.Errorf("a run within its budgets reports an overrun:\n%s", text)
	}
	if !strings.Contains(summary.String(), "| go test | 420 | 500 |") {
		t.Errorf("the summary lacks the go test step:\n%s", summary.String())
	}
	if !strings.Contains(summary.String(), "| se issue pull | 12 | 3600 |") {
		t.Errorf("the summary lacks issue pull's run:\n%s", summary.String())
	}
	// What land reads back is what was reported.
	loaded, ok, err := battery.Load(d, dir)
	if err != nil || !ok || loaded.TotalMs != 460 || len(loaded.Slowest) != 3 {
		t.Errorf("Load = %+v, %v, %v", loaded, ok, err)
	}
}

func TestASoftBudgetOverrunIsReportedButPasses(t *testing.T) {
	t.Parallel()
	d, dir := workspace(t, "biome\t40\ngo test\t1200\n", budgets)
	var summary bytes.Buffer
	p, err := battery.Report(d, dir, &summary)
	if err != nil {
		t.Fatalf("a soft overrun failed the battery: %v", err)
	}
	want := []string{"step go test took 1200ms, over its budget of 500ms", "the battery took 1240ms, over its budget of 1000ms"}
	if strings.Join(p.Overruns, "|") != strings.Join(want, "|") {
		t.Errorf("overruns = %q, want %q", p.Overruns, want)
	}
	if !strings.Contains(p.Text(), "battery: OVER BUDGET: step go test took 1200ms") {
		t.Errorf("the report does not show the overrun:\n%s", p.Text())
	}
	if !strings.Contains(summary.String(), "> **Over budget:** step go test took 1200ms") {
		t.Errorf("the summary does not show the overrun:\n%s", summary.String())
	}
}

func TestAHardBudgetOverrunFails(t *testing.T) {
	t.Parallel()
	d, dir := workspace(t, "go test\t1200\n", strings.Replace(budgets, "go test: {ms: 500, hard: false}", "go test: {ms: 500, hard: true}", 1))
	p, err := battery.Report(d, dir, nil)
	if err == nil || !strings.Contains(err.Error(), "step go test took 1200ms") {
		t.Fatalf("a hard overrun answered %v", err)
	}
	if len(p.Hard) != 1 {
		t.Errorf("hard overruns = %q", p.Hard)
	}
}

func TestNoProfileIsNoError(t *testing.T) {
	t.Parallel()
	if _, ok, err := battery.Load(disk.NewFake(), filepath.FromSlash("/ws")); ok || err != nil {
		t.Errorf("Load of an empty workspace = %v, %v", ok, err)
	}
}

func TestAStepLineThatIsNoStepIsRefused(t *testing.T) {
	t.Parallel()
	if _, err := battery.ParseSteps(strings.NewReader("biome 40\n")); err == nil {
		t.Error("a step without a tab was read")
	}
}

func TestRelayShowsPackagesAndFailuresAndKeepsEveryEvent(t *testing.T) {
	t.Parallel()
	var out, raw bytes.Buffer
	if err := battery.Relay(strings.NewReader(events+"not json\n"), &out, &raw); err != nil {
		t.Fatal(err)
	}
	if got, want := out.String(), "c.go:3: wrong\nFAIL\tp\t1.8s\nnot json\n"; got != want {
		t.Errorf("shown = %q, want %q", got, want)
	}
	if raw.String() != events+"not json\n" {
		t.Errorf("kept = %q", raw.String())
	}
}

func TestTheBudgetsFileBudgetsEveryStepOfTheBattery(t *testing.T) {
	t.Parallel()
	// This reads the checkout's own files, so it reads the real disk.
	b, err := battery.ReadBudgets(disk.Real(), "../../..")
	if err != nil {
		t.Fatal(err)
	}
	check, err := os.ReadFile("../../../tests/check.sh")
	if err != nil {
		t.Fatal(err)
	}
	if b.Total.Ms <= 0 {
		t.Error("the battery's total has no budget")
	}
	for _, line := range strings.Split(string(check), "\n") {
		if name, ok := strings.CutPrefix(line, `step "`); ok {
			name, _, _ = strings.Cut(name, `"`)
			if b.Steps[name].Ms <= 0 {
				t.Errorf("step %q has no budget in %s", name, battery.BudgetsFile)
			}
		}
	}
}
