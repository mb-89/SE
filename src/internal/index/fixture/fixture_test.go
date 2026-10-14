package fixture_test

import (
	"testing"

	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/index/fixture"
	"github.com/mb-89/SE/src/internal/index/indextest"
)

func TestTheFixturePassesAgainstTheFakeIndexAlone(t *testing.T) {
	t.Parallel()
	f, err := indextest.New(fixture.Module)
	if err != nil {
		t.Fatal(err)
	}
	if got, _ := f.Out("total"); got != (index.Value{V: 0}) {
		t.Fatalf("before it runs, total reads %+v, want its built-in 0, not provided", got)
	}
	must(t, f.Seed("numbers", []int{1, 2, 3}))
	must(t, f.Config("scale", 10))
	must(t, f.Derive("total"))
	if got, _ := f.Out("total"); got != (index.Value{V: 60, Provided: true}) {
		t.Fatalf("total is %+v, want 60, provided", got)
	}
	text, err := f.Call("tally note", "keep", "this")
	must(t, err)
	if text != `noted "keep this" beside 3 numbers` {
		t.Fatalf("the note answered %q", text)
	}
	if got, _ := f.Out("note"); got != (index.Value{V: "keep this", Provided: true}) {
		t.Fatalf("note is %+v", got)
	}
	if _, err := f.Call("tally note"); err == nil {
		t.Fatal("a note without words was taken")
	}
	if err := f.Seed("numbers", "three"); err == nil {
		t.Fatal("the fake took a string for []int")
	}
	if err := f.Seed("elsewhere", 1); err == nil {
		t.Fatal("the fake seeded a port the module does not read")
	}
}

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}
