package index_test

import (
	"strings"
	"testing"

	"github.com/mb-89/kern/index"
)

// An inlet and an ear for the host's events are an I/O component's alone.
func TestAnInletWithoutTheIOFlagIsRefused(t *testing.T) {
	t.Parallel()
	c := index.Declare("door", "Commits what comes in.",
		index.Inlet(func(string, index.Reader, index.Commit) error { return nil }))
	if err := c.Err(); err == nil || !strings.Contains(err.Error(), "carries no I/O flag") {
		t.Fatalf("the declaration answers %v, and wants it refused for its missing I/O flag", err)
	}
}

// The start hands each switched-on instance its commit and its config; it
// commits what comes in, and the instances that hear the host's events hear
// each one, a switched-off one none.
func TestAnInletCommitsAndTheInstancesHearTheHost(t *testing.T) {
	t.Parallel()
	heard := map[string][]string{}
	commits := map[string]index.Commit{}
	last := index.Output("last", "", "The last event heard.")
	door := index.Declare("door", "Commits the events it hears.",
		index.IO(), last,
		index.Config("prefix", "", "What each event is written after."),
		index.Inlet(func(instance string, read index.Reader, commit index.Commit) error {
			if read("config/prefix") != "seen " {
				t.Errorf("instance %s reads the prefix %v, and wants the wiring's", instance, read("config/prefix"))
			}
			commits[instance] = commit
			return nil
		}),
		index.Hears(func(instance, event string, payload []byte) error {
			heard[instance] = append(heard[instance], event+" "+string(payload))
			return commits[instance](last.Set("seen " + event))
		}),
	)
	w, err := index.ParseWiring([]byte(`
[instances.on]
component = "door"
config = { prefix = "seen " }

[instances.off]
component = "door"
enabled = false
config = { prefix = "seen " }
`))
	if err != nil {
		t.Fatal(err)
	}
	ix, err := index.Start(w, door)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := commits["off"]; ok || commits["on"] == nil {
		t.Fatalf("the start handed commits to %v, and wants the switched-on instance alone", commits)
	}
	if err := ix.Hear("PostToolUse", []byte(`{}`)); err != nil {
		t.Fatal(err)
	}
	if v, _ := ix.Read("on/last"); v.V != "seen PostToolUse" || len(heard["off"]) != 0 {
		t.Fatalf("on/last reads %v and off heard %q", v.V, heard["off"])
	}
}
