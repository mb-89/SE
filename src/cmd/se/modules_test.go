// Internal test package: package main cannot be imported.
package main

import (
	"bufio"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/io/clock"
)

// The wiring se carries starts the modules se carries, as the daemon starts
// them, so a broken catalog fails here before a merge.
func TestTheWiringSeCarriesStartsItsModules(t *testing.T) {
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
	if want := []string{"cli", "clock", "session", "sessionlog"}; !slices.Equal(instances, want) {
		t.Fatalf("the index runs %v, want %v", instances, want)
	}
}

// Every command se registers is declared on the index, and the index declares no other.
func TestTheIndexDeclaresEveryRegisteredCommand(t *testing.T) {
	var declared, registered []string
	for _, c := range catalog().Commands {
		declared = append(declared, c.Name)
		if want := declOf(commands[c.Name]); c.CommandDecl != want {
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
	at := time.Date(2026, 10, 14, 12, 0, 0, 0, time.UTC)
	old := wall
	wall = clock.NewFake(at)
	t.Cleanup(func() { wall = old })
	ws := t.TempDir()
	paths := daemon.Paths{Workspace: ws}
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
		time.Sleep(5 * time.Millisecond)
		ep, ok = daemon.Healthy(paths)
	}
	call := func(method, path, body string) string {
		t.Helper()
		req, err := http.NewRequest(method, "http://"+ep.Address+path, strings.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Authorization", "Bearer "+ep.Token)
		resp, err := (&http.Client{Transport: &http.Transport{Proxy: nil}}).Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		var out strings.Builder
		sc := bufio.NewScanner(resp.Body)
		for sc.Scan() {
			out.WriteString(sc.Text())
		}
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("%s %s: status %d, %s", method, path, resp.StatusCode, out.String())
		}
		return out.String()
	}
	for _, ev := range []string{"session.start", "tool.call", "tool.call"} {
		call(http.MethodPost, "/event", `{"session":"s1","event":"`+ev+`","at":"t","e":{"x":1}}`)
	}
	var started struct{ Value time.Time }
	if err := json.Unmarshal([]byte(call(http.MethodGet, "/value/clock/started", "")), &started); err != nil || !started.Value.Equal(at) {
		t.Errorf("clock/started reads %v, %v; want %v", started.Value, err, at)
	}
	call(http.MethodPost, "/shutdown", "")
	if code := <-served; code != 0 {
		t.Fatalf("se serve: exit %d", code)
	}
	log, err := os.ReadFile(filepath.Join(paths.Logs(), "s1.jsonl"))
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
