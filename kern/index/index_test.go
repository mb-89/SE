package index_test

import (
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/mb-89/kern/index"
	"github.com/mb-89/kern/index/fixture"
	"github.com/mb-89/kern/kerntest"
)

// source is a fixture component whose outputs a test commits, as an I/O component commits what comes in.
var source = index.Declare("source", "Holds what a test commits.",
	index.IO(),
	index.Output("n", 7, "A number."),
	index.Output("list", []int(nil), "Some numbers."),
)

type xIn struct {
	X int `index:"x"`
}

// doubler is a fixture component that reads one number by its own local name.
var doubler = index.Declare("doubler", "Doubles a number.",
	index.Derived("twice", 0, "Twice x.", func(in xIn) (int, error) { return 2 * in.X, nil }),
)

type pairIn struct {
	A int `index:"a"`
	B int `index:"b"`
}

// checker is a fixture component that records every pair it reads.
func checker(seen *[]pairIn) *index.Component {
	return index.Declare("checker", "Records what it reads.",
		index.Derived("sum", 0, "a plus b.", func(in pairIn) (int, error) {
			*seen = append(*seen, in)
			return in.A + in.B, nil
		}),
	)
}

func start(t *testing.T, wiring string, components ...*index.Component) *index.Index {
	t.Helper()
	w, err := index.ParseWiring([]byte(wiring))
	if err != nil {
		t.Fatal(err)
	}
	ix, err := index.Start(w, components...)
	if err != nil {
		t.Fatal(err)
	}
	return ix
}

func refused(t *testing.T, wiring string, want string, components ...*index.Component) {
	t.Helper()
	w, err := index.ParseWiring([]byte(wiring))
	if err != nil {
		t.Fatal(err)
	}
	_, err = index.Start(w, components...)
	if err == nil || !strings.Contains(err.Error(), want) {
		t.Fatalf("the start answered %v, want a refusal saying %q", err, want)
	}
}

func read(t *testing.T, ix *index.Index, name string) index.Value {
	t.Helper()
	v, err := ix.Read(name)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func must(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

const tallyWiring = `
[instances.numbers]
component = "source"

[instances.tally]
component = "tally"
config = { scale = 2 }

[wires]
"numbers.list" = "numbers/all"
"tally.numbers" = "numbers/all"
`

func TestAComponentRegistersAndCommitsItsOutputs(t *testing.T) {
	t.Parallel()
	if !slices.Contains(index.Registered(), fixture.Tally) {
		t.Fatal("the fixture's init registered nothing")
	}
	ix := start(t, tallyWiring, append(index.Registered(), source)...)
	must(t, ix.Commit("numbers", index.Write{Port: "list", Value: []int{1, 2}}))
	if got := read(t, ix, "tally/total"); got != (index.Value{V: 6, Provided: true}) {
		t.Fatalf("tally/total is %+v, want 6, provided", got)
	}
	if _, err := ix.Call("tally", "note", "hi"); err == nil {
		t.Fatal("a command was called by its first word alone")
	}
	r, err := ix.Call("tally note", "hi")
	must(t, err)
	if r.Text != `noted "hi" beside 2 numbers` || read(t, ix, "tally/note").V != "hi" {
		t.Fatalf("the note answered %q and committed %+v", r.Text, read(t, ix, "tally/note"))
	}
}

func TestANestedInstanceOwnsTheNamesUnderIt(t *testing.T) {
	t.Parallel()
	ix := start(t, `
[instances.issues]
component = "source"

[instances."issues/numbers"]
component = "source"

[instances."issues/pull"]
component = "tally"
config = { scale = 2 }

[wires]
"issues/pull.numbers" = "issues/numbers.list"
`, fixture.Tally, source)
	must(t, ix.Commit("issues/numbers", index.Write{Port: "list", Value: []int{2, 3}}))
	for name, want := range map[string]index.Value{
		"issues/n":                 {V: 7},
		"issues/numbers/list":      {V: []int{2, 3}, Provided: true},
		"issues/pull/total":        {V: 10, Provided: true},
		"issues/pull/config/scale": {V: 2, Provided: true},
	} {
		if got := read(t, ix, name); !reflect.DeepEqual(got, want) {
			t.Errorf("%s reads %+v, want %+v", name, got, want)
		}
	}
	for _, c := range []struct{ wiring, want string }{
		{`instances = { issues = { component = "source" }, "issues/pull" = { component = "source" } }
wires = { "issues.n" = "issues/pull/n" }`, "name issues/pull/n lies under instance issues/pull, which owns the names issues/pull/...: issues.n may not write it"},
		{`instances = { a = { component = "source" }, "a/n" = { component = "source" } }`, "name a/n lies under instance a/n, which owns the names a/n/...: a.n may not write it"},
		{`instances = { t = { component = "tally" }, "t/config" = { component = "source" } }
wires = { "t.numbers" = "built-in" }`, "name t/config/scale lies under instance t/config, which owns the names t/config/...: the config of t may not write it"},
		{`instances = { "issues//pull" = { component = "source" } }`, `instance "issues//pull" needs a name`},
		{`instances = { "issues/<id>" = { component = "source" } }`, `instance "issues/<id>" needs a name`},
		{`instances = { "/pull" = { component = "source" } }`, `instance "/pull" needs a name`},
	} {
		refused(t, c.wiring, c.want, fixture.Tally, source)
	}
}

// The catalog check refuses a name with two writers, naming both wires' lines.
func TestASecondWriterForANameIsRefused(t *testing.T) {
	t.Parallel()
	refused(t, `
[instances.a]
component = "source"

[instances.b]
component = "source"

[wires]
"a.n" = "shared"
"b.n" = "shared"
`, "wiring line 10: name shared has two writers: a.n (line 9) and b.n", source)
	refused(t, `instances = { a = { component = "source" }, b = { component = "source" } }
wires = { "a.n" = "b.n" }`, "both outputs", source)
	ix := start(t, tallyWiring, fixture.Tally, source)
	if err := ix.Commit("tally", index.Write{Port: "total", Value: 1}); err == nil {
		t.Fatal("a commit to an output its derivation writes was taken")
	}
	if err := ix.Commit("numbers", index.Write{Port: "total", Value: 1}); err == nil {
		t.Fatal("a commit to a port the instance does not write was taken")
	}
	if err := ix.Commit("numbers", index.Write{Port: "n", Value: "seven"}); err == nil {
		t.Fatal("a commit of the wrong type was taken")
	}
}

// The catalog check refuses an input bound to nothing, naming the instance's
// line, and an input bound to a name nothing writes, naming the wire's.
func TestAnInputBoundToNothingIsRefused(t *testing.T) {
	t.Parallel()
	refused(t, `
[instances.d]
component = "doubler"
`, "wiring line 2: input d.x is bound to nothing: wire it, or mark it built-in", doubler)
	refused(t, `
[instances.d]
component = "doubler"

[wires]
"d.x" = "nowhere"
`, "wiring line 6: input d.x is bound to nowhere, which nothing writes", doubler)
	refused(t, `instances = { d = { component = "doubler" }, e = { component = "doubler" } }
wires = { "d.x" = "e.x", "e.x" = "built-in" }`, "d.x is bound to e.x, which is no output: an input bound to nothing", doubler)
}

func TestAReaderGetsTheBuiltInValueWhileNothingIsProvided(t *testing.T) {
	t.Parallel()
	ix := start(t, `
instances = { src = { component = "source" }, d = { component = "doubler" }, e = { component = "doubler" } }
wires = { "d.x" = "src.n", "e.x" = "built-in" }
`, source, doubler)
	if got := read(t, ix, "src/n"); got != (index.Value{V: 7}) {
		t.Fatalf("src/n is %+v, want its built-in 7, not provided", got)
	}
	if got := read(t, ix, "d/twice"); got != (index.Value{V: 14, Provided: true}) {
		t.Fatalf("d/twice is %+v, want 14 from the built-in 7", got)
	}
	if got := read(t, ix, "e/twice"); got != (index.Value{V: 0, Provided: true}) {
		t.Fatalf("e/twice is %+v, want 0 from an input left built-in", got)
	}
	if _, err := ix.Read("src/nothing"); err == nil {
		t.Fatal("a name nobody declared was read")
	}
}

// Waves: a derivation runs once per change, lowest height first, and never
// reads a new value beside a stale one.
func TestSnapshotsAreConsistent(t *testing.T) {
	t.Parallel()
	var seen []pairIn
	// c reads n twice: straight, and through d. It must never see a new n beside an old 2n.
	ix := start(t, `
instances = { src = { component = "source" }, d = { component = "doubler" }, c = { component = "checker" } }
wires = { "src.n" = "n", "d.x" = "n", "c.a" = "n", "c.b" = "d.twice" }
`, source, doubler, checker(&seen))
	before := ix.Snapshot()
	var pushed []any
	cancel, err := ix.Subscribe("c/sum", func(v index.Value) { pushed = append(pushed, v.V) })
	must(t, err)
	for n := 1; n <= 3; n++ {
		must(t, ix.Commit("src", index.Write{Port: "n", Value: n}))
	}
	must(t, ix.Commit("src", index.Write{Port: "n", Value: 3}))
	want := []pairIn{{7, 14}, {1, 2}, {2, 4}, {3, 6}}
	if !reflect.DeepEqual(seen, want) {
		t.Fatalf("c read %v, want each n beside its own 2n, once per change: %v", seen, want)
	}
	if !reflect.DeepEqual(pushed, []any{3, 6, 9}) {
		t.Fatalf("c/sum pushed %v, want 3 6 9 and nothing for the unchanged commit", pushed)
	}
	if v, _ := before.Read("n"); v.V != 7 || before.Revision() >= ix.Snapshot().Revision() {
		t.Fatalf("the old snapshot moved: n reads %v at %d", v.V, before.Revision())
	}
	cancel()
	must(t, ix.Commit("src", index.Write{Port: "n", Value: 4}))
	if len(pushed) != 3 {
		t.Fatal("a cancelled subscriber was told")
	}
}

func TestTheWiringBindsByLocalNames(t *testing.T) {
	t.Parallel()
	// doubler reads "x" and source writes "n": only the wiring knows they meet.
	ix := start(t, `
instances = { src = { component = "source" }, d = { component = "doubler" } }
wires = { "d.x" = "src.n", "d.twice" = "results/double" }
`, source, doubler)
	must(t, ix.Commit("src", index.Write{Port: "n", Value: 21}))
	if got := read(t, ix, "results/double"); got.V != 42 {
		t.Fatalf("results/double is %+v, want 42", got)
	}
	for _, c := range []struct{ wiring, want string }{
		{`instances = { d = { component = "tally" } }`, "no component tally is registered"},
		{`instances = { s = { component = "source" }, d = { component = "doubler" } }
wires = { "d.x" = "s.list" }`, "two types on one wire: d.x reads s/list as int, but s.list writes []int"},
		{`instances = { d = { component = "doubler" }, e = { component = "doubler" } }
wires = { "d.x" = "e.twice", "e.x" = "d.twice" }`, "a cycle: d reads e reads d"},
		{`instances = { d = { component = "doubler" } }
wires = { "d.y" = "built-in" }`, "instance d has no port y"},
		{`instances = { d = { component = "doubler", config = { scale = 2 } } }
wires = { "d.x" = "built-in" }`, "component doubler has no config key scale"},
	} {
		refused(t, c.wiring, c.want, source, doubler)
	}
}

func TestABrokenDeclarationIsRefused(t *testing.T) {
	t.Parallel()
	type untagged struct{ X int }
	broken := index.Declare("broken", "",
		index.Output("o", 0, ""),
		index.Derived("d", 0, "help", func(untagged) (int, error) { return 0, nil }),
		index.Command(index.CommandDecl{Name: "broken"}, func(xIn, []string) (index.Result, error) { return index.Result{}, nil }),
		index.Request[string, int]("o", ""),
		index.Verb("v", "", func(string) (int, error) { return 0, nil }),
	)
	for _, want := range []string{
		"component broken has no help", "output o has no help", "tagged index", `command "broken" has no summary`,
		`command "broken" has no class`, "request port o has no help", "request port o is also an input or an output",
		"verb v has no help", "accepts verbs but carries no I/O flag",
	} {
		refused(t, `instances = { b = { component = "broken" } }`, want, broken)
	}
	if _, err := kerntest.New(broken); err == nil {
		t.Fatal("the fake took a broken component")
	}
	refused(t, `instances = { a = { component = "source" } }`, "two components are named source", source, source)
}

func TestAFixtureComponentsCommandReachesTheCollector(t *testing.T) {
	t.Parallel()
	c := start(t, tallyWiring, fixture.Tally, source).Catalog()
	got, ok := c.Command("tally note")
	if !ok || got.Instance != "tally" || got.Summary != "Take a note." || got.Group != "Fixtures" {
		t.Fatalf("the collector has %+v", got)
	}
	if len(c.Session()) != 1 {
		t.Fatalf("offered in a session %v", c.Session())
	}
	if c.Instances[1].Name != "tally" || c.Instances[1].Inputs[0].Name != "tally/config/scale" || c.Instances[1].Inputs[1].Name != "numbers/all" {
		t.Fatalf("the catalog binds tally as %+v", c.Instances[1])
	}
	if !c.Instances[0].IO || c.Instances[1].IO {
		t.Fatalf("the I/O flag reads %v for source and %v for tally", c.Instances[0].IO, c.Instances[1].IO)
	}
	refused(t, `instances = { a = { component = "tally" }, b = { component = "tally" } }
wires = { "a.numbers" = "built-in", "b.numbers" = "built-in" }`,
		`command "tally note" is declared by a and b`, fixture.Tally)
}

// The fake core speaks the contract the index speaks: the same inputs make the same outputs.
func TestTheFakeAndTheCoreAgree(t *testing.T) {
	t.Parallel()
	ix := start(t, tallyWiring, fixture.Tally, source)
	must(t, ix.Commit("numbers", index.Write{Port: "list", Value: []int{4, 5}}))
	core, err := ix.Call("tally note", "same")
	must(t, err)
	f, err := kerntest.New(fixture.Tally)
	must(t, err)
	must(t, f.Seed("numbers", []int{4, 5}))
	must(t, f.Config("scale", 2))
	must(t, f.Derive("total"))
	fake, err := f.Call("tally note", "same")
	must(t, err)
	total, _ := f.Out("total")
	if fake != core.Text || total != read(t, ix, "tally/total") {
		t.Fatalf("the fake answered %q and %+v, the core %q and %+v", fake, total, core.Text, read(t, ix, "tally/total"))
	}
}

// The collector gathers what the components declared without running them, and refuses what Start refuses.
func TestCollectGathersTheCatalogAndRunsNothing(t *testing.T) {
	t.Parallel()
	var seen []pairIn
	w, err := index.ParseWiring([]byte(`instances = { c = { component = "checker" } }
wires = { "c.a" = "built-in", "c.b" = "built-in" }`))
	must(t, err)
	c, err := index.Collect(w, checker(&seen))
	must(t, err)
	if len(c.Instances) != 1 || c.Instances[0].Outputs[0].Name != "c/sum" || len(seen) != 0 {
		t.Fatalf("the catalog is %+v, and the derivation ran on %v", c, seen)
	}
	w, err = index.ParseWiring([]byte(`instances = { c = { component = "checker" } }`))
	must(t, err)
	if _, err := index.Collect(w, checker(&seen)); err == nil || !strings.Contains(err.Error(), "input c.a is bound to nothing") {
		t.Fatalf("the collector answered %v for an unbound input", err)
	}
}

// posts is a fixture output that commits a number at a key, as an I/O component commits what comes in.
var posts = index.Family("posts", 0, "The last number posted at a key.")

var poster = index.Declare("poster", "Holds the numbers a test posts at keys.", index.IO(), posts)

// A family is declared once; its keys come and go without a name added at
// runtime, each reads its own value, and a derivation that reads the family
// runs once per key that changed, on that key's value.
func TestAFamilyHoldsAValuePerKey(t *testing.T) {
	t.Parallel()
	ix := start(t, `
instances = { p = { component = "poster" }, s = { component = "source" }, d = { component = "doubler" } }
wires = { "p.posts" = "posts/<id>/last", "d.x" = "posts/<id>/last" }
`, poster, source, doubler)
	if got := read(t, ix, "posts/a/last"); got != (index.Value{V: 0}) {
		t.Fatalf("posts/a/last before any post is %+v, want the built-in 0, not provided", got)
	}
	var pushed []any
	cancel, err := ix.Subscribe("posts/b/last", func(v index.Value) { pushed = append(pushed, v.V) })
	must(t, err)
	defer cancel()
	must(t, ix.Commit("p", posts.At("a", 3)))
	if got := read(t, ix, "d/twice"); got.V != 6 {
		t.Fatalf("d/twice after a post at a is %+v, want 6", got)
	}
	must(t, ix.Commit("p", posts.At("b", 5)))
	if got := read(t, ix, "d/twice"); got.V != 10 {
		t.Fatalf("d/twice after a post at b is %+v, want 10", got)
	}
	for name, want := range map[string]int{"posts/a/last": 3, "posts/b/last": 5} {
		if got := read(t, ix, name); got != (index.Value{V: want, Provided: true}) {
			t.Fatalf("%s is %+v, want %d, provided", name, got, want)
		}
	}
	must(t, ix.Commit("p", posts.Drop("b")))
	if got := read(t, ix, "posts/b/last"); got != (index.Value{V: 0}) {
		t.Fatalf("posts/b/last after its key went is %+v, want the built-in 0, not provided", got)
	}
	if got := read(t, ix, "d/twice"); got.V != 0 {
		t.Fatalf("d/twice after b went is %+v, want 0 from the built-in", got)
	}
	must(t, ix.Commit("p", posts.Drop("b")))
	if !reflect.DeepEqual(pushed, []any{5, 0}) {
		t.Fatalf("posts/b/last pushed %v, want 5, then 0 once as its key went", pushed)
	}
	for _, name := range []string{"posts/<id>/last", "posts/a/b/last", "posts/../last"} {
		if _, err := ix.Read(name); err == nil {
			t.Fatalf("%s was read", name)
		}
	}
	for _, w := range []index.Write{posts.At("", 1), posts.At("..", 1), {Port: "posts", Value: 1}} {
		if err := ix.Commit("p", w); err == nil {
			t.Fatalf("a commit at key %q was taken", w.Key)
		}
	}
	if err := ix.Commit("s", index.Write{Port: "n", Value: 1, Key: "a"}); err == nil {
		t.Fatal("a commit at a key to no family was taken")
	}
	if err := ix.Commit("s", index.Write{Port: "n", Gone: true}); err == nil {
		t.Fatal("a drop from no family was taken")
	}
}

func TestABrokenFamilyIsRefused(t *testing.T) {
	t.Parallel()
	for _, c := range []struct{ wiring, want string }{
		{`instances = { p = { component = "poster" } }
wires = { "p.posts" = "posts/last" }`, `p.posts writes at keys, and "posts/last" is no family`},
		{`instances = { s = { component = "source" } }
wires = { "s.n" = "n/<id>" }`, `s.n writes no keys, and "n/<id>" is a family`},
		{`instances = { p = { component = "poster" } }
wires = { "p.posts" = "posts/<a>/<b>" }`, "is no name"},
		{`instances = { p = { component = "poster" }, q = { component = "poster" } }
wires = { "p.posts" = "posts/<a>", "q.posts" = "posts/<b>" }`, "families posts/<a> and posts/<b> hold the same names"},
		{`instances = { p = { component = "poster" }, s = { component = "source" } }
wires = { "p.posts" = "posts/<a>", "s.n" = "posts/one" }`, "name posts/one lies in family posts/<a>"},
		{`instances = { p = { component = "poster" }, t = { component = "tally" } }
wires = { "p.posts" = "posts/<a>", "t.numbers" = "posts/<a>" }`, "a command reads it"},
	} {
		refused(t, c.wiring, c.want, poster, source, fixture.Tally)
	}
}

// The fake core keeps what a command writes to a family at its key.
func TestTheFakeKeepsAFamilyByKey(t *testing.T) {
	t.Parallel()
	f, err := kerntest.New(index.Declare("post", "Posts 1 at its argument.", posts,
		index.Command(index.CommandDecl{Name: "post", Usage: "post <key>", Summary: "Post.", Help: "Posts 1 at key.", Group: "Fixtures", Class: index.Batch},
			func(_ struct{}, args []string) (index.Result, error) {
				return index.Result{Writes: []index.Write{posts.At(args[0], 1)}}, nil
			})))
	must(t, err)
	_, err = f.Call("post", "a")
	must(t, err)
	if got, err := f.OutAt("posts", "a"); err != nil || got != (index.Value{V: 1, Provided: true}) {
		t.Fatalf("posts at a is %+v, %v", got, err)
	}
	if got, err := f.OutAt("posts", "b"); err != nil || got != (index.Value{V: 0}) {
		t.Fatalf("posts at b is %+v, %v", got, err)
	}
	if _, err := f.Out("posts"); err == nil {
		t.Fatal("a family was read without a key")
	}
}

type allIn struct {
	All map[string]int `index:"all"`
}

// summer is a fixture component that reads the family posts whole.
func summer(runs *int) *index.Component {
	return index.Declare("summer", "Sums every number posted.",
		index.Derived("sum", 0, "The sum over every key.", func(in allIn) (int, error) {
			*runs++
			n := 0
			for _, v := range in.All {
				n += v
			}
			return n, nil
		}),
	)
}

// An input of type map[string]T bound to a family of T reads it whole: every
// key standing, once per change at any key, so a derivation can count across
// keys; a command may read a family that way too.
func TestAnInputReadsAFamilyWhole(t *testing.T) {
	t.Parallel()
	runs := 0
	ix := start(t, `
instances = { p = { component = "poster" }, s = { component = "summer" } }
wires = { "p.posts" = "posts/<id>", "s.all" = "posts/<id>" }
`, poster, summer(&runs))
	if got := read(t, ix, "s/sum"); got.V != 0 {
		t.Fatalf("s/sum before any post is %+v, want 0", got)
	}
	before := runs
	must(t, ix.Commit("p", posts.At("a", 3)))
	must(t, ix.Commit("p", posts.At("b", 5)))
	if got := read(t, ix, "s/sum"); got.V != 8 {
		t.Fatalf("s/sum after posts at a and b is %+v, want 8", got)
	}
	if runs-before != 2 {
		t.Fatalf("the derivation ran %d times for two commits, want once each", runs-before)
	}
	must(t, ix.Commit("p", posts.Drop("a")))
	if got := read(t, ix, "s/sum"); got.V != 5 {
		t.Fatalf("s/sum after a went is %+v, want 5", got)
	}
	refused(t, `
instances = { p = { component = "poster" }, s = { component = "summer" } }
wires = { "p.posts" = "posts/<id>", "s.all" = "posts/<id>/x" }
`, "which nothing writes", poster, summer(&runs))
}
