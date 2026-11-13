package index_test

import (
	"context"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/kern/index"
	"github.com/mb-89/kern/index/fixture"
	"github.com/mb-89/kern/kerntest"
)

const clerkWiring = `
[instances.ledger]
component = "ledger"

[instances.clerk]
component = "clerk"

[wires]
"clerk.post" = "ledger.append"
`

// A command answers requests on its own request ports; the core delivers them
// in order to the verbs the wiring binds, and the continuation reads the answers.
func TestACommandsRequestsGoOutInOrderAndItsContinuationReadsTheAnswers(t *testing.T) {
	t.Parallel()
	var lines []string
	ix := start(t, clerkWiring, fixture.Clerk, fixture.Ledger(&lines))
	r, err := ix.Call("clerk file", "one", "two", "three")
	must(t, err)
	if !reflect.DeepEqual(lines, []string{"one", "two", "three"}) {
		t.Fatalf("the ledger holds %v", lines)
	}
	if r.Text != "filing 3 words\nfiled three as line 3" || len(r.Requests) != 3 {
		t.Fatalf("the command answered %q with requests %v", r.Text, r.Requests)
	}
	if got := read(t, ix, "clerk/filed"); got != (index.Value{V: "three as line 3", Provided: true}) {
		t.Fatalf("clerk/filed is %+v", got)
	}
	got, ok := ix.Catalog().Command("clerk file")
	if !ok || got.Instance != "clerk" {
		t.Fatalf("the collector has %+v", got)
	}
	in := ix.Catalog().Instances
	if in[0].Requests[0].Verb != "ledger.append" || in[1].Verbs[0].Verb != "append" {
		t.Fatalf("the catalog shows the clerk's requests %+v and the ledger's verbs %+v", in[0].Requests, in[1].Verbs)
	}
}

// A failed request stops the list: the command fails with its reason, and
// nothing already delivered is undone.
func TestAFailedRequestStopsTheListWithoutUndo(t *testing.T) {
	t.Parallel()
	var lines []string
	ix := start(t, clerkWiring, fixture.Clerk, fixture.Ledger(&lines))
	r, err := ix.Call("clerk file", "one", "", "three")
	if err == nil || !strings.Contains(err.Error(), "request 2 of 3, clerk.post to ledger.append, failed: the ledger takes no empty line") {
		t.Fatalf("the command answered %v", err)
	}
	if !reflect.DeepEqual(lines, []string{"one"}) || len(r.Requests) != 1 {
		t.Fatalf("the ledger holds %v after %v", lines, r.Requests)
	}
	if got := read(t, ix, "clerk/filed"); got.Provided {
		t.Fatalf("the continuation ran after a failed request: %+v", got)
	}
}

func TestABrokenRequestWireIsRefused(t *testing.T) {
	t.Parallel()
	var lines []string
	other := index.Declare("other", "Takes numbers.", index.IO(),
		index.Verb("count", "Counts.", func(_ context.Context, n int) (int, error) { return n, nil }))
	for _, c := range []struct{ wiring, want string }{
		{`instances = { clerk = { component = "clerk" } }`, "wiring line 1: request port clerk.post is bound to nothing"},
		{`instances = { clerk = { component = "clerk" }, s = { component = "source" } }
wires = { "clerk.post" = "s.n" }`, "request port clerk.post is bound to s.n, which is no verb"},
		{`instances = { clerk = { component = "clerk" }, o = { component = "other" } }
wires = { "clerk.post" = "o.count" }`, "two types on one wire: clerk.post sends string and reads int, but o.count takes int and answers int"},
		{`instances = { clerk = { component = "clerk" }, ledger = { component = "ledger" } }
wires = { "clerk.post" = { to = "ledger.append", builtin = true } }`, "clerk.post is no input: only an input may go without its writer"},
		{`instances = { ledger = { component = "ledger" } }
wires = { "ledger.append" = "x" }`, "instance ledger has no port append"},
	} {
		refused(t, c.wiring, c.want, fixture.Clerk, fixture.Ledger(&lines), source, other)
	}
	ix := start(t, clerkWiring, fixture.Clerk, fixture.Ledger(&lines))
	if err := ix.Commit("clerk", index.Write{Port: "post", Value: "x"}); err == nil {
		t.Fatal("a request port was committed as an output")
	}
	bad := index.Declare("bad", "Asks wrongly.", fixture.Post,
		index.Command(index.CommandDecl{Name: "bad", Usage: "bad", Summary: "Ask.", Help: "Asks.", Group: "Fixtures", Class: index.Batch},
			func(_ struct{}, _ []string) (index.Result, error) {
				return index.Result{Requests: []index.Ask{{Port: "post", Value: 3}}}, nil
			}))
	ix = start(t, `instances = { bad = { component = "bad" }, ledger = { component = "ledger" } }
wires = { "bad.post" = "ledger.append" }`, bad, fixture.Ledger(&lines))
	if _, err := ix.Call("bad"); err == nil || !strings.Contains(err.Error(), "request port post sends string, not int") {
		t.Fatalf("a request of the wrong type answered %v", err)
	}
}

// The fake core hands each request the answer the test gives it, so the
// continuation runs, and records the requests in order.
func TestTheFakeAnswersRequestsAndAgreesWithTheCore(t *testing.T) {
	t.Parallel()
	f, err := kerntest.New(fixture.Clerk)
	must(t, err)
	if _, err := f.Call("clerk file", "a"); err == nil || !strings.Contains(err.Error(), "request port post has no answer") {
		t.Fatalf("an unanswered request answered %v", err)
	}
	f, err = kerntest.New(fixture.Clerk)
	must(t, err)
	n := 0
	must(t, f.Answer("post", func(req any) (any, error) { n++; return n, nil }))
	fake, err := f.Call("clerk file", "one", "two", "three")
	must(t, err)
	if want := []index.Ask{fixture.Post.Ask("one"), fixture.Post.Ask("two"), fixture.Post.Ask("three")}; !reflect.DeepEqual(f.Requests(), want) {
		t.Fatalf("the fake recorded %v", f.Requests())
	}
	var lines []string
	core, err := start(t, clerkWiring, fixture.Clerk, fixture.Ledger(&lines)).Call("clerk file", "one", "two", "three")
	must(t, err)
	filed, _ := f.Out("filed")
	if fake != core.Text || filed != (index.Value{V: "three as line 3", Provided: true}) {
		t.Fatalf("the fake answered %q and %+v, the core %q", fake, filed, core.Text)
	}
	if err := f.Answer("nope", nil); err == nil {
		t.Fatal("the fake answered a port the component does not declare")
	}
	f, err = kerntest.New(fixture.Clerk)
	must(t, err)
	must(t, f.Answer("post", func(any) (any, error) { return "many", nil }))
	if _, err := f.Call("clerk file", "a"); err == nil || !strings.Contains(err.Error(), "reads int, and its answerer gave string") {
		t.Fatalf("an answer of the wrong type answered %v", err)
	}
}
