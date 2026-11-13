// Package agreement holds SE's two fleet paths to one answer: the Go
// components (fleet, retro) and the Python fallback (scripts/work_tickets.py
// fleet_findings, scripts/retro.py landed_since_retro) read the same
// GitHub snapshot names, testdata/snapshot.json, and must find the same.
package agreement

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/se/components/fleet"
	"github.com/mb-89/se/components/retro"
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
	Issues     map[string]github.Snapshot `json:"issues"`
	Pulls      map[string]github.Snapshot `json:"pulls"`
	Checks     map[string]github.Snapshot `json:"checks"`
	Branches   map[string]time.Time       `json:"branches"`
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

// pythonPaths is what the Python paths answer on the fixture.
type pythonPaths struct {
	Fleet struct {
		Healthy  bool            `json:"healthy"`
		Findings []fleet.Finding `json:"findings"`
	} `json:"fleet"`
	Retro int `json:"retro"`
}

func runPython(t *testing.T) pythonPaths {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(python(t), filepath.Join("testdata", "python_paths.py"), root, filepath.Join("testdata", "snapshot.json"))
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
// snapshot, finding for finding, word for word; the fixture holds every kind.
func TestTheFleetPathsAgree(t *testing.T) {
	f := load(t)
	got := fleet.Check(fleet.In{Issues: f.Issues, Pulls: f.Pulls, Checks: f.Checks, Branches: f.Branches,
		LeaseHours: f.LeaseHours, Repository: f.Repository, Base: f.Base}, f.Now)
	want := runPython(t)
	if got.Healthy != want.Fleet.Healthy || !reflect.DeepEqual(got.Findings, want.Fleet.Findings) {
		g, _ := json.MarshalIndent(got.Findings, "", " ")
		w, _ := json.MarshalIndent(want.Fleet.Findings, "", " ")
		t.Fatalf("the paths disagree:\nGo (healthy %v):\n%s\nPython (healthy %v):\n%s", got.Healthy, g, want.Fleet.Healthy, w)
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

// The retro component and retro.py count the same work issues landed since
// the last retro on one snapshot.
func TestTheRetroPathsAgree(t *testing.T) {
	f := load(t)
	got := retro.Count(retro.In{Issues: f.Issues, Pulls: f.Pulls, DueAfter: f.DueAfter, Tracker: f.Tracker, Base: f.Base})
	want := runPython(t)
	if got.Landed != want.Retro {
		t.Fatalf("the retro component counts %d landed, retro.py %d", got.Landed, want.Retro)
	}
	if got.Landed == 0 || !got.Due || got.Retro != 20 {
		t.Fatalf("on the fixture the count is %+v, want landed above 0, due, since retro #20", got)
	}
}
