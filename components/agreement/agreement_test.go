// Package agreement holds SE's two fleet paths to one answer: the Go
// components (fleet, retro-due) and the Python fallback (scripts/work_tickets.py
// fleet_findings, scripts/retro.py retro_countdown, scripts/overhaul.py
// overhaul_countdown) read the same GitHub snapshot names,
// testdata/snapshot.json, and must find the same.
package agreement

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"kern/components/github"
	"se/components/fleet"
	retrodue "se/components/retro-due"
)

// PythonEnv names the Python the test runs SE's scripts with; where unset,
// the first of python3 and python on the path that has tomllib (3.11+), as
// kern's contract suite looks for one.
const PythonEnv = "KERN_PYTHON"

type fixture struct {
	Now        time.Time                  `json:"now"`
	LeaseHours float64                    `json:"lease_hours"`
	Repository string                     `json:"repository"`
	Base       string                     `json:"base"`
	Tracker    string                     `json:"tracker"`
	DueAfter   int                        `json:"due_after"`
	Overhaul   int                        `json:"overhaul_after"`
	Issues     map[string]github.Snapshot `json:"issues"`
	Pulls      map[string]github.Snapshot `json:"pulls"`
	Checks     map[string]github.Snapshot `json:"checks"`
	Branches   map[string]time.Time       `json:"branches"`
	// The countdowns' settings beside due_after and overhaul_after, which
	// countdownFixture adds.
	FailureWeight int `json:"failure_weight"`
	Days          int `json:"days"`
	OverhaulDays  int `json:"overhaul_days"`
}

func load(t *testing.T) fixture {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("testdata", "snapshot.json"))
	if err != nil {
		t.Fatal(err)
	}
	var f fixture
	if err := json.Unmarshal(data, &f); err != nil {
		t.Fatal(err)
	}
	return f
}

func python(t *testing.T) string {
	t.Helper()
	if p := os.Getenv(PythonEnv); p != "" {
		return p
	}
	for _, name := range []string{"python3", "python"} {
		if p, err := exec.LookPath(name); err == nil && exec.Command(p, "-c", "import tomllib").Run() == nil {
			return p
		}
	}
	t.Fatalf("no Python 3.11 or later: set %s, or put python3 on the path", PythonEnv)
	return ""
}

// countdown is a countdown as retro.py and overhaul.py answer it (Countdown).
type countdown struct {
	SinceRun int    `json:"since_run"`
	Landed   int    `json:"landed"`
	Failed   int    `json:"failed"`
	Count    int    `json:"count"`
	Due      bool   `json:"due"`
	Reason   string `json:"reason"`
	Open     []int  `json:"open"`
}

// pythonPaths is what the Python paths answer on the fixture.
type pythonPaths struct {
	Fleet struct {
		Healthy  bool            `json:"healthy"`
		Findings []fleet.Finding `json:"findings"`
	} `json:"fleet"`
	Retro    countdown `json:"retro"`
	Overhaul countdown `json:"overhaul"`
}

// countdownFixture is testdata/snapshot.json with the countdowns' settings
// (failure weight 5, 7 days, 30 overhaul days), written to a file of its own;
// without the open retro, it also holds an escalated work issue updated since
// the newest retro started, so every part of the count is counted.
func countdownFixture(t *testing.T, openRetro bool) (string, fixture) {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("testdata", "snapshot.json"))
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		t.Fatal(err)
	}
	raw["failure_weight"], raw["days"], raw["overhaul_days"] = 5, 7, 30
	issues := raw["issues"].(map[string]any)
	if !openRetro {
		delete(issues, "alice.se.30")
		issues["alice.se.40"] = map[string]any{"repo": "alice/se", "number": 40, "read": "2026-11-13T11:59:00Z", "via": "token",
			"data": map[string]any{"number": 40, "title": "feat/x", "state": "open", "body": "",
				"created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-11-08T00:00:00Z",
				"labels": []any{map[string]any{"name": "work"}, map[string]any{"name": "escalated"}}}}
	}
	out, err := json.Marshal(raw)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "snapshot.json")
	if err := os.WriteFile(path, out, 0o644); err != nil {
		t.Fatal(err)
	}
	var f fixture
	if err := json.Unmarshal(out, &f); err != nil {
		t.Fatal(err)
	}
	return path, f
}

// runPython runs the Python paths on the fixture; with ages, the fleet check
// runs with se.toml [fleet] ages on.
func runPython(t *testing.T, ages ...bool) pythonPaths {
	t.Helper()
	path, _ := countdownFixture(t, true)
	return runPythonOn(t, path, ages...)
}

// runPythonOn runs the Python paths on the fixture at path.
func runPythonOn(t *testing.T, path string, ages ...bool) pythonPaths {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	args := []string{filepath.Join("testdata", "python_paths.py"), root, path}
	if len(ages) > 0 && ages[0] {
		args = append(args, "--ages")
	}
	cmd := exec.Command(python(t), args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("the Python paths failed: %v\n%s", err, stderr.String())
	}
	var p pythonPaths
	if err := json.Unmarshal(out, &p); err != nil {
		t.Fatalf("the Python paths answered no JSON: %v\n%s", err, out)
	}
	return p
}

// The fleet component and the Python fleet check find the same on one
// snapshot, finding for finding, word for word, with the setting ages off
// and on; the fixture holds every kind.
func TestTheFleetPathsAgree(t *testing.T) {
	f := load(t)
	var got fleet.Findings
	for _, ages := range []bool{false, true} {
		got = fleet.Check(fleet.In{Issues: f.Issues, Pulls: f.Pulls, Checks: f.Checks, Branches: f.Branches,
			LeaseHours: f.LeaseHours, Repository: f.Repository, Base: f.Base, Ages: ages}, f.Now)
		want := runPython(t, ages)
		if got.Healthy != want.Fleet.Healthy || !reflect.DeepEqual(got.Findings, want.Fleet.Findings) {
			g, _ := json.MarshalIndent(got.Findings, "", " ")
			w, _ := json.MarshalIndent(want.Fleet.Findings, "", " ")
			t.Fatalf("with ages %v the paths disagree:\nGo (healthy %v):\n%s\nPython (healthy %v):\n%s", ages, got.Healthy, g, want.Fleet.Healthy, w)
		}
		person := ""
		for _, finding := range got.Findings {
			if finding.Kind == "waiting on the person" {
				person = finding.What
			}
		}
		if open := strings.Contains(person, ", open 13 days"); open != ages {
			t.Fatalf("with ages %v the person finding reads %q", ages, person)
		}
	}
	kinds := map[string]bool{}
	for _, finding := range got.Findings {
		kinds[finding.Kind] = true
	}
	for _, k := range fleet.Kinds {
		if !kinds[k] {
			t.Errorf("the fixture holds no %q finding: extend testdata/snapshot.json", k)
		}
	}
}

// The retro-due component and retro.py count the same that came back since the
// newest retro started on one snapshot: with its open retro, which resets the
// count, and without it, where landings and a failure count and make a retro
// due.
func TestTheRetroPathsAgree(t *testing.T) {
	for _, openRetro := range []bool{true, false} {
		path, f := countdownFixture(t, openRetro)
		got := retrodue.Count(retrodue.In{Issues: f.Issues, Pulls: f.Pulls, DueAfter: f.DueAfter, FailureWeight: f.FailureWeight,
			Days: f.Days, Tracker: f.Tracker, Base: f.Base}, f.Now)
		want := runPythonOn(t, path).Retro
		mine := countdown{SinceRun: got.Retro, Landed: got.Landed, Failed: got.Failed, Count: got.Count, Due: got.Due,
			Reason: got.Reason, Open: got.Open}
		if !reflect.DeepEqual(mine, want) {
			t.Fatalf("with the open retro %v the paths disagree:\nGo %+v\nPython %+v", openRetro, mine, want)
		}
		if openRetro && (got.Retro != 30 || got.Count != 0 || got.Due || len(got.Open) != 1) {
			t.Fatalf("with the open retro the count is %+v, want reset at retro #30, open, not due", got)
		}
		// #32 closed as a duplicate starts nothing; #19 and #20 started together, and the first wins.
		if !openRetro && (got.Landed == 0 || got.Failed != 1 || !got.Due || got.Retro != 19) {
			t.Fatalf("without it the count is %+v, want landings and a failure since retro #19, due", got)
		}
	}
}

// The retro-due component and overhaul.py count the same retros closed since
// the newest overhaul started on one snapshot; the fixture holds a retro
// closed as a duplicate, which neither counts.
func TestTheOverhaulPathsAgree(t *testing.T) {
	path, f := countdownFixture(t, true)
	got := retrodue.Count(retrodue.In{Issues: f.Issues, Pulls: f.Pulls, DueAfter: f.DueAfter, OverhaulAfter: f.Overhaul,
		OverhaulDays: f.OverhaulDays, Tracker: f.Tracker, Base: f.Base}, f.Now)
	want := runPythonOn(t, path).Overhaul
	mine := countdown{SinceRun: got.Overhaul, Count: got.Retros, Due: got.OverhaulDue, Reason: got.OverhaulReason,
		Open: got.OverhaulOpen}
	if !reflect.DeepEqual(mine, want) {
		t.Fatalf("the paths disagree:\nGo %+v\nPython %+v", mine, want)
	}
	if got.Retros != 2 || !got.OverhaulDue || got.Overhaul != 31 {
		t.Fatalf("on the fixture the overhaul count is %+v, want 2 retros since overhaul #31, due after 2", got)
	}
}
