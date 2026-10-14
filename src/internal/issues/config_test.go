// Internal test package: it reuses the recorded answers of the cadence tests.
package issues

import (
	"testing"
	"time"

	"github.com/mb-89/SE/src/index"
)

// The values are the issues instance's config keys: the wiring se
// carries gives their built-in values, and a wiring that sets one is read.
func TestTheCadencesTheLeaseAndTheCapAreConfigValues(t *testing.T) {
	t.Parallel()
	s, err := Configured()
	if err != nil || s != Builtin() || s.Parallel != 4 {
		t.Fatalf("the wiring se carries: %+v %v, want %+v", s, err, Builtin())
	}
	w, err := index.ParseWiring([]byte("instances:\n  issues: { module: issues, config: { lease: 1h, retro-cadence: 2, overhaul-cadence: 3, max-filed: 1, manifest-target: 30m, paused: true, parallel: 2 } }\n"))
	if err != nil {
		t.Fatal(err)
	}
	want := Settings{RetroCadence: 2, OverhaulCadence: 3, MaxFiled: 1, Lease: time.Hour, ManifestTarget: 30 * time.Minute, Paused: true, Parallel: 2}
	if s, err = From(w); err != nil || s != want {
		t.Fatalf("set by the wiring: %+v %v, want %+v", s, err, want)
	}
	if w, err = index.ParseWiring([]byte("instances:\n  issues: { module: issues, config: { lease: soon } }\n")); err != nil {
		t.Fatal(err)
	}
	if _, err = From(w); err == nil {
		t.Fatal("a lease that is no duration was read")
	}
}

// A source runs on the config it is handed: a cadence of 3 makes four
// closed retros an overhaul due.
func TestASourceReadsItsCadenceFromItsConfig(t *testing.T) {
	t.Parallel()
	cfg := Builtin()
	cfg.OverhaulCadence = 3
	o, err := Source{Proc: machine, Repo: repo, GitHub: recorded(t, overhaulRepo(4, 0)), Clock: atNow(), Config: &cfg}.OverhaulCadence()
	if err != nil || o.Every != 3 || !o.Due() {
		t.Fatalf("%+v %v", o, err)
	}
}
