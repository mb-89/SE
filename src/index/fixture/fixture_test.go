package fixture_test

import (
	"testing"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/index/fixture"
	"github.com/mb-89/SE/src/index/indextest"
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

func TestTheFixtureRunsAsANestedInstanceAndOwnsTheNamesUnderIt(t *testing.T) {
	t.Parallel()
	w, err := index.ParseWiring([]byte(`
instances:
  fixtures/tally: {module: tally, config: {scale: 3}}
wires:
  fixtures/tally.numbers: built-in
`))
	must(t, err)
	ix, err := index.Start(w, fixture.Module)
	must(t, err)
	_, err = ix.Call("tally note", "nested")
	must(t, err)
	for name, want := range map[string]index.Value{
		"fixtures/tally/total":        {V: 0, Provided: true},
		"fixtures/tally/note":         {V: "nested", Provided: true},
		"fixtures/tally/config/scale": {V: 3, Provided: true},
	} {
		if got, err := ix.Read(name); err != nil || got != want {
			t.Errorf("%s reads %+v (%v), want %+v", name, got, err, want)
		}
	}
	c := ix.Catalog()
	if len(c.Instances) != 1 || c.Instances[0].Name != "fixtures/tally" || c.Instances[0].Outputs[0].Name != "fixtures/tally/note" {
		t.Fatalf("the catalog shows %+v", c.Instances)
	}
	if cmd, ok := c.Command("tally note"); !ok || cmd.Instance != "fixtures/tally" {
		t.Fatalf("tally note is answered by %+v", cmd)
	}
}

type echoIn struct {
	Word string `index:"word"`
}

func TestTheFakeIndexTakesANestedModule(t *testing.T) {
	t.Parallel()
	echo := index.Declare("fixtures/echo", "Says its word back.",
		index.Derived("said", "", "The word, said back.", func(in echoIn) (string, error) { return in.Word, nil }))
	f, err := indextest.New(echo)
	must(t, err)
	must(t, f.Seed("word", "hi"))
	must(t, f.Derive("said"))
	if got, _ := f.Out("said"); got != (index.Value{V: "hi", Provided: true}) {
		t.Fatalf("said is %+v", got)
	}
	for _, name := range []string{"fixtures//echo", "/echo", "fixtures/", "fixtures/<id>", "fixtures.echo"} {
		if _, err := indextest.New(index.Declare(name, "Bad.")); err == nil {
			t.Errorf("the fake took a module named %q", name)
		}
	}
}
