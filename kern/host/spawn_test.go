package host_test

import (
	"fmt"
	"os"
	"runtime"
	"testing"
	"time"

	"kern/host"
)

// spawnedArg makes this test binary a core that host.Start spawned: it is
// called `<bin> serve --root <root> kern-test-spawned` and serves root until
// it is stopped.
const spawnedArg = "kern-test-spawned"

func spawned() int {
	c, err := host.Serve(host.Options{Root: os.Args[len(os.Args)-2]})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	<-c.Ended()
	return 0
}

// A stop of a core that a long-lived process spawned, as the MCP door does,
// returns as soon as the core has ended: its starter reaps it, so no zombie
// answers the stop's wait for its pid. Unix only: on Windows the starter is
// a shell that has exited long before.
func TestAStopOfACoreItsLiveStarterSpawnedReturnsAtOnce(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("on Windows the core's starter, a shell, has exited; nothing waits to reap it")
	}
	t.Parallel()
	root := t.TempDir()
	t.Cleanup(func() { _, _ = host.AskStop(root) })
	got, err := host.Start(host.Wall{}, root, os.Args[0], spawnedArg)
	if err != nil || got != host.Spawned {
		t.Fatalf("the start answers %v, %v, and wants %v", got, err, host.Spawned)
	}
	for end := time.Now().Add(wait); ; time.Sleep(10 * time.Millisecond) {
		if _, err := host.ReadStanding(root); err == nil {
			break
		}
		if time.Now().After(end) {
			t.Fatalf("the spawned core wrote no standing file within %v", wait)
		}
	}
	asked := time.Now()
	pid, err := host.AskStop(root)
	if err != nil {
		t.Fatalf("the stop of the spawned core: %v", err)
	}
	if took := time.Since(asked); took > host.HangUp+2*time.Second {
		t.Fatalf("the stop of pid %d returns %v after it was asked, and wants about %v", pid, took, host.HangUp)
	}
}
