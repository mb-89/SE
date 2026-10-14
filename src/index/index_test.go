package index_test

import (
	"fmt"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/index/fixture"
	"github.com/mb-89/SE/src/index/indextest"
	_ "github.com/mb-89/SE/src/internal/guidance" // the wiring se carries instances it
)

// source is a fixture module whose outputs a test commits, as an I/O module commits what comes in.
var source = index.Declare("source", "Holds what a test commits.",
	index.IO(),
	index.Output("n", 7, "A number."),
	index.Output("list", []int(nil), "Some numbers."),
)

type xIn struct {
	X int `index:"x"`
}

// doubler is a fixture module that reads one number by its own local name.
var doubler = index.Declare("doubler", "Doubles a number.",
	index.Derived("twice", 0, "Twice x.", func(in xIn) (int, error) { return 2 * in.X, nil }),
)

type pairIn struct {
	A int `index:"a"`
	B int `index:"b"`
}

// checker is a fixture module that records every pair it reads.
func checker(seen *[]pairIn) *index.Module {
	return index.Declare("checker", "Records what it reads.",
		index.Derived("sum", 0, "a plus b.", func(in pairIn) (int, error) {
			*seen = append(*seen, in)
			return in.A + in.B, nil
		}),
	)
}

func start(t *testing.T, wiring string, modules ...*index.Module) *index.Index {
	t.Helper()
	w, err := index.ParseWiring([]byte(wiring))
	if err != nil {
		t.Fatal(err)
	}
	ix, err := index.Start(w, modules...)
	if err != nil {
		t.Fatal(err)
	}
	return ix
}

func refused(t *testing.T, wiring string, want string, modules ...*index.Module) {
	t.Helper()
	w, err := index.ParseWiring([]byte(wiring))
	if err != nil {
		t.Fatal(err)
	}
	_, err = index.Start(w, modules...)
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
instances:
  numbers: {module: source}
  tally: {module: tally, config: {scale: 2}}
wires:
  numbers.list: numbers/all
  tally.numbers: numbers/all
`

func TestAModuleRegistersAndCommitsItsOutputs(t *testing.T) {
	t.Parallel()
	if !slices.Contains(index.Registered(), fixture.Module) {
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
instances:
  issues: {module: source}
  issues/numbers: {module: source}
  issues/pull: {module: tally, config: {scale: 2}}
wires:
  issues/pull.numbers: issues/numbers.list
`, fixture.Module, source)
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
		{"instances: {issues: {module: source}, issues/pull: {module: source}}\nwires: {issues.n: issues/pull/n}", "name issues/pull/n lies under instance issues/pull, which owns the names issues/pull/...: issues.n may not write it"},
		{"instances: {a: {module: source}, a/n: {module: source}}", "name a/n lies under instance a/n, which owns the names a/n/...: a.n may not write it"},
		{"instances: {t: {module: tally}, t/config: {module: source}}\nwires: {t.numbers: built-in}", "name t/config/scale lies under instance t/config, which owns the names t/config/...: the config of t may not write it"},
		{"instances: {issues//pull: {module: source}}", `instance "issues//pull" needs a name`},
		{"instances: {issues/<id>: {module: source}}", `instance "issues/<id>" needs a name`},
		{"instances: {/pull: {module: source}}", `instance "/pull" needs a name`},
	} {
		refused(t, c.wiring, c.want, fixture.Module, source)
	}
}

func TestASecondWriterForANameIsRefused(t *testing.T) {
	t.Parallel()
	refused(t, `
instances:
  a: {module: source}
  b: {module: source}
wires:
  a.n: shared
  b.n: shared
`, "wiring line 7: name shared has two writers: a.n (line 6) and b.n", source)
	refused(t, "instances: {a: {module: source}, b: {module: source}}\nwires: {a.n: b.n}\n", "both outputs", source)
	ix := start(t, tallyWiring, fixture.Module, source)
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

func TestAReaderGetsTheBuiltInValueWhileNothingIsProvided(t *testing.T) {
	t.Parallel()
	ix := start(t, `
instances:
  src: {module: source}
  d: {module: doubler}
  e: {module: doubler}
wires:
  d.x: src.n
  e.x: built-in
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

func TestSnapshotsAreConsistent(t *testing.T) {
	t.Parallel()
	var seen []pairIn
	// c reads n twice: straight, and through d. It must never see a new n beside an old 2n.
	ix := start(t, `
instances:
  src: {module: source}
  d: {module: doubler}
  c: {module: checker}
wires:
  src.n: n
  d.x: n
  c.a: n
  c.b: d.twice
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
instances:
  src: {module: source}
  d: {module: doubler}
wires:
  d.x: src.n
  d.twice: results/double
`, source, doubler)
	must(t, ix.Commit("src", index.Write{Port: "n", Value: 21}))
	if got := read(t, ix, "results/double"); got.V != 42 {
		t.Fatalf("results/double is %+v, want 42", got)
	}
	for _, c := range []struct{ wiring, want string }{
		{"instances: {d: {module: doubler}}", "wiring line 1: input d.x is bound to nothing"},
		{"instances: {d: {module: doubler}}\nwires: {d.x: nowhere}", "input d.x is bound to nowhere, which nothing writes"},
		{"instances: {d: {module: tally}}", "no module tally is registered"},
		{"instances: {s: {module: source}, d: {module: doubler}}\nwires: {d.x: s.list}", "two types on one wire: d.x reads s/list as int, but s.list writes []int"},
		{"instances: {d: {module: doubler}, e: {module: doubler}}\nwires: {d.x: e.twice, e.x: d.twice}", "a cycle: d reads e reads d"},
		{"instances: {d: {module: doubler}}\nwires: {d.y: built-in}", "instance d has no port y"},
		{"instances: {d: {module: doubler, config: {scale: 2}}}\nwires: {d.x: built-in}", "module doubler has no config key scale"},
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
		index.Command(index.CommandDecl{Name: "broken"}, func(xIn, index.Args) (index.Result, error) { return index.Result{}, nil }),
	)
	for _, want := range []string{"module broken has no help", "output o has no help", "tagged index", `command "broken" has no summary`, `command "broken" has no class`} {
		refused(t, "instances: {b: {module: broken}}", want, broken)
	}
	if _, err := indextest.New(broken); err == nil {
		t.Fatal("the fake took a broken module")
	}
}

func TestAFixtureModulesCommandReachesTheCollector(t *testing.T) {
	t.Parallel()
	c := start(t, tallyWiring, fixture.Module, source).Catalog()
	got, ok := c.Command("tally note")
	if !ok || got.Instance != "tally" || got.Summary != "Take a note." || got.Group != "Fixtures" {
		t.Fatalf("the collector has %+v", got)
	}
	if len(c.Session()) != 1 || len(c.Buttons()) != 0 {
		t.Fatalf("offered in a session %v, as buttons %v", c.Session(), c.Buttons())
	}
	if c.Instances[1].Name != "tally" || c.Instances[1].Inputs[0].Name != "tally/config/scale" || c.Instances[1].Inputs[1].Name != "numbers/all" {
		t.Fatalf("the catalog binds tally as %+v", c.Instances[1])
	}
	if !c.Instances[0].IO || c.Instances[1].IO {
		t.Fatalf("the I/O flag reads %v for source and %v for tally", c.Instances[0].IO, c.Instances[1].IO)
	}
	refused(t, "instances: {a: {module: tally}, b: {module: tally}}\nwires: {a.numbers: built-in, b.numbers: built-in}",
		`command "tally note" is declared by a and b`, fixture.Module)
}

// The fake index speaks the contract the core speaks: the same inputs make the same outputs.
func TestTheFakeAndTheCoreAgree(t *testing.T) {
	t.Parallel()
	ix := start(t, tallyWiring, fixture.Module, source)
	must(t, ix.Commit("numbers", index.Write{Port: "list", Value: []int{4, 5}}))
	core, err := ix.Call("tally note", "same")
	must(t, err)
	f, err := indextest.New(fixture.Module)
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

// The collector gathers what the modules declared without running them, and refuses what Start refuses.
func TestCollectGathersTheCatalogAndRunsNothing(t *testing.T) {
	t.Parallel()
	var seen []pairIn
	w, err := index.ParseWiring([]byte("instances: {c: {module: checker}}\nwires: {c.a: built-in, c.b: built-in}"))
	must(t, err)
	c, err := index.Collect(w, checker(&seen))
	must(t, err)
	if len(c.Instances) != 1 || c.Instances[0].Outputs[0].Name != "c/sum" || len(seen) != 0 {
		t.Fatalf("the catalog is %+v, and the derivation ran on %v", c, seen)
	}
	w, err = index.ParseWiring([]byte("instances: {c: {module: checker}}"))
	must(t, err)
	if _, err := index.Collect(w, checker(&seen)); err == nil || !strings.Contains(err.Error(), "input c.a is bound to nothing") {
		t.Fatalf("the collector answered %v for an unbound input", err)
	}
}

// posts is a fixture module that commits a number at a key, as an I/O module commits what comes in.
var posts = index.Family("posts", 0, "The last number posted at a key.")

var poster = index.Declare("poster", "Holds the numbers a test posts at keys.", index.IO(), posts)

// A family is declared once; its keys come and go without a name added at
// runtime, each reads its own value, and a derivation that reads the family
// runs once per key that changed, on that key's value.
func TestAFamilyHoldsAValuePerKey(t *testing.T) {
	t.Parallel()
	ix := start(t, `
instances:
  p: {module: poster}
  s: {module: source}
  d: {module: doubler}
wires:
  p.posts: posts/<id>/last
  d.x: posts/<id>/last
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
		{"instances: {p: {module: poster}}\nwires: {p.posts: posts/last}", `p.posts writes at keys, and "posts/last" is no family`},
		{"instances: {s: {module: source}}\nwires: {s.n: n/<id>}", `s.n writes no keys, and "n/<id>" is a family`},
		{"instances: {p: {module: poster}}\nwires: {p.posts: posts/<a>/<b>}", "is no name"},
		{"instances: {p: {module: poster}, q: {module: poster}}\nwires: {p.posts: posts/<a>, q.posts: posts/<b>}", "families posts/<a> and posts/<b> hold the same names"},
		{"instances: {p: {module: poster}, s: {module: source}}\nwires: {p.posts: posts/<a>, s.n: posts/one}", "name posts/one lies in family posts/<a>"},
		{"instances: {p: {module: poster}, t: {module: tally}}\nwires: {p.posts: posts/<a>, t.numbers: posts/<a>}", "a command reads it"},
	} {
		refused(t, c.wiring, c.want, poster, source, fixture.Module)
	}
}

// The fake index keeps what a command writes to a family at its key.
func TestTheFakeKeepsAFamilyByKey(t *testing.T) {
	t.Parallel()
	f, err := indextest.New(index.Declare("post", "Posts 1 at its argument.", posts,
		index.Command(index.CommandDecl{Name: "post", Usage: "post <key>", Summary: "Post.", Help: "Posts 1 at key.", Group: "Fixtures", Class: index.Batch, Words: index.AnyWords},
			func(_ struct{}, args index.Args) (index.Result, error) {
				return index.Result{Writes: []index.Write{posts.At(args.Words[0], 1)}}, nil
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

// shelf is a fixture I/O module that answers how many of a thing it holds,
// takes things out, and records each request it answered.
func shelf(log *[]string) *index.Module {
	stock := map[string]int{"apples": 3, "pears": 1}
	return index.Declare("shelf", "Holds things, counted.",
		index.IO(),
		index.Verb("count", "How many of a thing it holds.", func(thing string) (int, error) {
			*log = append(*log, "count "+thing)
			return stock[thing], nil
		}),
		index.Verb("take", "Takes one of a thing out.", func(thing string) (int, error) {
			*log = append(*log, "take "+thing)
			if stock[thing] == 0 {
				return 0, fmt.Errorf("no %s left", thing)
			}
			stock[thing]--
			return stock[thing], nil
		}),
	)
}

var (
	count = index.Ask[string, int]("count", "Counts a thing on the shelf.")
	take  = index.Ask[string, int]("take", "Takes a thing off the shelf.")
	taken = index.Output("taken", "", "What the last shop took.")
)

// shopper is a fixture compute module whose command counts what it is asked
// for, then takes each one there is, through its request ports alone.
var shopper = index.Declare("shopper", "Takes what the shelf holds.",
	count, take, taken,
	index.Command(index.CommandDecl{
		Name: "shop", Usage: "shop THING...", Summary: "Take things.", Help: "Counts each thing, then takes one of each there is.",
		Group: "Fixtures", Class: index.Batch, Words: index.AnyWords,
	}, func(_ struct{}, args index.Args) (index.Result, error) {
		var counts []index.Request
		for _, w := range args.Words {
			counts = append(counts, count.Of(w))
		}
		return index.Result{Requests: counts, Then: func(answers []any) (index.Result, error) {
			var takes []index.Request
			var got []string
			for i, a := range answers {
				if count.Answer(a) > 0 {
					takes = append(takes, take.Of(args.Words[i]))
					got = append(got, args.Words[i])
				}
			}
			return index.Result{Requests: takes, Then: func(left []any) (index.Result, error) {
				return index.Result{
					Text:   fmt.Sprintf("took %s, %d requests", strings.Join(got, " and "), len(args.Words)+len(left)),
					Writes: []index.Write{taken.Set(strings.Join(got, " "))},
				}, nil
			}}, nil
		}}, nil
	}),
)

const shopWiring = `
instances:
  shelf: {module: shelf}
  shopper: {module: shopper}
wires:
  shopper.count: shelf.count
  shopper.take: shelf.take
`

// A command's requests reach the verbs the wiring binds its ports to, in
// order, and each continuation reads the answers of the list before it.
func TestACommandsRequestsReachTheVerbsInOrder(t *testing.T) {
	t.Parallel()
	var log []string
	ix := start(t, shopWiring, shelf(&log), shopper)
	r, err := ix.Call("shop", "apples", "plums", "pears")
	must(t, err)
	if want := []string{"count apples", "count plums", "count pears", "take apples", "take pears"}; !slices.Equal(log, want) {
		t.Fatalf("the shelf answered %v, want %v", log, want)
	}
	if r.Text != "took apples and pears, 5 requests" || len(r.Requests) != 0 || r.Then != nil {
		t.Fatalf("the shop answered %+v", r)
	}
	if got := read(t, ix, "shopper/taken"); got != (index.Value{V: "apples pears", Provided: true}) {
		t.Fatalf("shopper/taken reads %+v", got)
	}
	c := ix.Catalog()
	for _, in := range c.Instances {
		switch in.Name {
		case "shopper":
			if len(in.Asks) != 2 || in.Asks[0].Name != "count" || in.Asks[0].Verb != "shelf.count" {
				t.Errorf("the catalog shows shopper's request ports as %+v", in.Asks)
			}
		case "shelf":
			if len(in.Verbs) != 2 || in.Verbs[1].Name != "take" || in.Verbs[1].Help == "" {
				t.Errorf("the catalog shows shelf's verbs as %+v", in.Verbs)
			}
		}
	}
}

// A failed request stops the list: the command fails with its reason, no
// later request goes out, and nothing the run wrote is committed.
func TestAFailedRequestStopsTheList(t *testing.T) {
	t.Parallel()
	var log []string
	failing := index.Declare("greedy", "Takes twice.", take, taken,
		index.Command(index.CommandDecl{Name: "grab", Usage: "grab", Summary: "Grab.", Help: "Takes a plum, then an apple.", Group: "Fixtures", Class: index.Batch},
			func(struct{}, index.Args) (index.Result, error) {
				return index.Result{Writes: []index.Write{taken.Set("all")}, Requests: []index.Request{take.Of("plums"), take.Of("apples")}}, nil
			}))
	ix := start(t, "instances: {shelf: {module: shelf}, greedy: {module: greedy}}\nwires: {greedy.take: shelf.take}", shelf(&log), failing)
	_, err := ix.Call("grab")
	if err == nil || !strings.Contains(err.Error(), "take: no plums left") {
		t.Fatalf("the grab answered %v, want the failed take's reason", err)
	}
	if !slices.Equal(log, []string{"take plums"}) {
		t.Fatalf("the shelf answered %v after the failure", log)
	}
	if got := read(t, ix, "greedy/taken"); got.Provided {
		t.Fatalf("a failed run committed %+v", got)
	}
}

func TestABrokenRequestWireIsRefused(t *testing.T) {
	t.Parallel()
	var log []string
	refused(t, "instances: {shelf: {module: shelf}, shopper: {module: shopper}}\nwires: {shopper.count: shelf.count}",
		"request port shopper.take is bound to no verb", shelf(&log), shopper)
	refused(t, "instances: {shelf: {module: shelf}, shopper: {module: shopper}}\nwires: {shopper.count: shelf.count, shopper.take: shelf.nothing}",
		"request port shopper.take is bound to shelf.nothing, which is no verb", shelf(&log), shopper)
	wrong := index.Declare("scale", "Weighs things.", index.IO(),
		index.Verb("count", "Weighs a thing.", func(string) (float64, error) { return 0, nil }))
	refused(t, "instances: {scale: {module: scale}, shelf: {module: shelf}, shopper: {module: shopper}}\nwires: {shopper.count: scale.count, shopper.take: shelf.take}",
		"two types on one wire: request port shopper.count takes string and answers int, but verb scale.count takes string and answers float64", wrong, shelf(&log), shopper)
	pure := index.Declare("pure", "Answers without the I/O flag.",
		index.Verb("count", "Counts.", func(string) (int, error) { return 0, nil }))
	if err := pure.Err(); err == nil || !strings.Contains(err.Error(), "carries no I/O flag") {
		t.Fatalf("a verb on a compute module was declared: %v", err)
	}
	twice := index.Declare("twice", "Names a port twice.", index.Ask[string, int]("taken", "Asks."), taken)
	if err := twice.Err(); err == nil || !strings.Contains(err.Error(), "request port taken is also an output") {
		t.Fatalf("a request port named as an output was declared: %v", err)
	}
}

// The fake index hands each request the test's answer, records it, and runs
// the continuations as the core does.
func TestTheFakeAnswersRequestsAsTheCoreDoes(t *testing.T) {
	t.Parallel()
	var log []string
	ix := start(t, shopWiring, shelf(&log), shopper)
	core, err := ix.Call("shop", "apples", "plums", "pears")
	must(t, err)
	f, err := indextest.New(shopper)
	must(t, err)
	if err := f.Answer("nothing", nil); err == nil {
		t.Fatal("the fake took an answer for a port the module does not declare")
	}
	stock := map[string]int{"apples": 3, "pears": 1}
	must(t, f.Answer("count", func(r any) (any, error) { return stock[r.(string)], nil }))
	must(t, f.Answer("take", func(r any) (any, error) { return stock[r.(string)] - 1, nil }))
	fake, err := f.Call("shop", "apples", "plums", "pears")
	must(t, err)
	if fake != core.Text {
		t.Fatalf("the fake answered %q, the core %q", fake, core.Text)
	}
	if got := f.Asked(); len(got) != 5 || got[3] != take.Of("apples") {
		t.Fatalf("the fake recorded %+v", got)
	}
	must(t, f.Answer("take", func(any) (any, error) { return "three", nil }))
	if _, err := f.Call("shop", "apples"); err == nil || !strings.Contains(err.Error(), "request port take answers int, not string") {
		t.Fatalf("the fake took an answer of the wrong type: %v", err)
	}
	g, err := indextest.New(shelf(&log))
	must(t, err)
	if n, err := g.Serve("count", "apples"); err != nil || n != 3 {
		t.Fatalf("the shelf served %v, %v", n, err)
	}
	if _, err := g.Serve("count", 3); err == nil {
		t.Fatal("the shelf served a request of the wrong type")
	}
}
