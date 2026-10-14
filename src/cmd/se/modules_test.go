// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/modules/io/clock"
	sehttp "github.com/mb-89/SE/src/modules/io/http"
)

// The wiring se carries starts the modules se carries, as the daemon starts
// them, so a broken catalog fails here before a merge.
func TestTheWiringSeCarriesStartsItsModules(t *testing.T) {
	t.Parallel()
	w, err := index.Wired()
	if err != nil {
		t.Fatal(err)
	}
	ix, err := index.Start(w, modules(daemon.Paths{Workspace: t.TempDir()}, clock.NewFake(time.Time{}))...)
	if err != nil {
		t.Fatal(err)
	}
	var instances []string
	for _, in := range ix.Catalog().Instances {
		instances = append(instances, in.Name)
	}
	if want := []string{"cli", "guidance", "io/clock", "io/disk", "io/env", "io/git", "io/github", "io/http", "io/proc", "io/session", "io/session-log", "issues", "reuse"}; !slices.Equal(instances, want) {
		t.Fatalf("the index runs %v, want %v", instances, want)
	}
}

// Every command se registers is declared on the index, and the index declares no other.
func TestTheIndexDeclaresEveryRegisteredCommand(t *testing.T) {
	t.Parallel()
	var declared, registered []string
	for _, c := range catalog().Commands {
		declared = append(declared, c.Name)
		if want := declOf(commands[c.Name]); !reflect.DeepEqual(c.CommandDecl, want) {
			t.Errorf("%s is declared as %+v, registered as %+v", c.Name, c.CommandDecl, want)
		}
	}
	for name := range commands {
		registered = append(registered, name)
	}
	slices.Sort(registered)
	if !slices.Equal(declared, registered) {
		t.Fatalf("the index declares %v, se registered %v", declared, registered)
	}
}

// se serve hosts the index: each event the bridgehead posts lands as the
// session log module's input and is written to its session's log, and the
// clock's start reads by name.
func TestServeLogsEachPostedEventThroughTheIndex(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)
	n, w := sehttp.NewFake(), worldOf(t)
	w.Clock, w.Net = clock.NewFake(at), n
	d, ws := onFake(t), "/ws"
	paths := daemon.Paths{Workspace: ws, Disk: d}
	served := make(chan int, 1)
	go func() {
		code, _, _ := se(t, "serve", "--workspace", ws, "--idle", "0")
		served <- code
	}()
	var ep daemon.Endpoint
	for ok := false; !ok; {
		select {
		case code := <-served:
			t.Fatalf("se serve ended at start: exit %d", code)
		default:
		}
		runtime.Gosched()
		ep, ok = daemon.Healthy(paths, n)
	}
	for _, ev := range []string{"session.start", "tool.call", "tool.call"} {
		if err := n.Event(ep.Address, ep.Token, daemon.Event{Session: "s1", Event: ev, At: "t", E: json.RawMessage(`{"x":1}`)}); err != nil {
			t.Fatal(err)
		}
	}
	v, err := n.Value(ep.Address, ep.Token, "io/clock/started")
	if started, _ := time.Parse(time.RFC3339, fmt.Sprint(v.Value)); err != nil || !started.Equal(at) {
		t.Errorf("io/clock/started reads %v, %v; want %v", v.Value, err, at)
	}
	if err := n.Shutdown(ep.Address, ep.Token); err != nil {
		t.Fatal(err)
	}
	if code := <-served; code != 0 {
		t.Fatalf("se serve: exit %d", code)
	}
	log, err := d.ReadFile(filepath.Join(paths.Logs(), "s1.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	var lines []string
	for _, ev := range []string{"session.start", "tool.call", "tool.call"} {
		lines = append(lines, `{"at":"t","e":{"x":1},"event":"`+ev+`"}`+"\n")
	}
	if string(log) != strings.Join(lines, "") {
		t.Fatalf("the log reads %q", log)
	}
}
