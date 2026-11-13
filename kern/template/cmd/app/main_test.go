package main

import (
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// The bare application starts on its own wiring with the components it
// registers, none yet, and answers its health until it is stopped.
func TestTheCoreStartsOnTheApplicationsWiring(t *testing.T) {
	w, err := index.ReadWiring(filepath.Join("..", "..", index.WiringFile))
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	core, err := host.Serve(host.Options{Root: root, Wiring: w, Components: index.Registered(), Log: io.Discard})
	if err != nil {
		t.Fatal(err)
	}
	if h := core.Health(); h.Pid != os.Getpid() || len(h.Instances) != 0 {
		t.Errorf("health of the bare application: %+v", h)
	}
	if _, err := os.Stat(host.StandingPath(root)); err != nil {
		t.Errorf("no standing file: %v", err)
	}
	core.Stop("test")
	select {
	case <-core.Ended():
	case <-time.After(10 * time.Second):
		t.Fatal("the core did not end within 10 s of its stop")
	}
}
