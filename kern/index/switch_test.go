package index_test

import (
	"strings"
	"testing"

	"github.com/mb-89/kern/index"
	"github.com/mb-89/kern/index/fixture"
)

// The catalog check refuses a wire to a switched-off instance, naming the
// wire's line and the switch's line.
func TestAWireToASwitchedOffInstanceIsRefused(t *testing.T) {
	t.Parallel()
	refused(t, `
[instances.src]
component = "source"
enabled = false

[instances.d]
component = "doubler"

[wires]
"d.x" = "src.n"
`, "wiring line 10: input d.x is bound to src/n, and its writer src is switched off on line 4", source, doubler)
	var lines []string
	refused(t, `
[instances.ledger]
component = "ledger"
enabled = false

[instances.clerk]
component = "clerk"

[wires]
"clerk.post" = "ledger.append"
`, "wiring line 10: request port clerk.post is bound to ledger.append, and ledger is switched off on line 4", fixture.Clerk, fixture.Ledger(&lines))
}

// An input that may go without its writer reads the built-in value, marked
// not provided, while that writer is switched off; a switched-off instance
// runs nothing, takes no commit and offers no command.
func TestASwitchedOffInstanceReadsAsItsBuiltInValues(t *testing.T) {
	t.Parallel()
	ix := start(t, `
[instances.src]
component = "source"
enabled = false

[instances.d]
component = "doubler"

[instances.off]
component = "doubler"
enabled = false

[instances.t]
component = "tally"
enabled = false

[wires]
"d.x" = { to = "src.n", builtin = true }
"off.x" = "src.n"
"t.numbers" = "built-in"
`, source, doubler, fixture.Tally)
	if got := read(t, ix, "src/n"); got != (index.Value{V: 7}) {
		t.Fatalf("src/n is %+v, want its built-in 7, not provided", got)
	}
	if got := read(t, ix, "d/twice"); got != (index.Value{V: 14, Provided: true}) {
		t.Fatalf("d/twice is %+v, want 14 from src's built-in 7", got)
	}
	if got := read(t, ix, "off/twice"); got != (index.Value{V: 0}) {
		t.Fatalf("off/twice is %+v: a switched-off derivation ran", got)
	}
	if err := ix.Commit("src", index.Write{Port: "n", Value: 1}); err == nil || !strings.Contains(err.Error(), "instance src is switched off (wiring line 4)") {
		t.Fatalf("a commit to a switched-off instance answered %v", err)
	}
	if _, err := ix.Call("tally note", "x"); err == nil {
		t.Fatal("a switched-off instance's command was called")
	}
	for _, in := range ix.Catalog().Instances {
		if in.Enabled != (in.Name == "d") {
			t.Fatalf("the catalog shows %s switched on: %v", in.Name, in.Enabled)
		}
	}
	ix = start(t, `
instances = { src = { component = "source" }, d = { component = "doubler" } }
wires = { "d.x" = { to = "src.n", builtin = true } }
`, source, doubler)
	must(t, ix.Commit("src", index.Write{Port: "n", Value: 4}))
	if got := read(t, ix, "d/twice"); got.V != 8 {
		t.Fatalf("d/twice is %+v, want 8: a wire that may go without its writer still reads it while it is on", got)
	}
}
