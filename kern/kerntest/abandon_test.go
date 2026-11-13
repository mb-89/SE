package kerntest_test

import (
	"context"
	"errors"
	"testing"

	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
	"github.com/mb-89/kern/kerntest"
)

// A call the fake gives up as the core does: call.core.abandon's
// (Abandon) ends a command waiting on its request, and the dead-caller
// check's (Gone) hands a verb's code its call's context, done with the
// cause the core names, so a component's test exercises both.
func TestTheFakeGivesACallUpAsTheCoreDoes(t *testing.T) {
	q := index.Request[string, string]("ask", "A question.")
	asker := index.Declare("asker", "Asks.", q,
		index.Command(index.CommandDecl{Name: "ask it", Usage: "ask it WORD", Summary: "Ask.", Help: "Asks, answers the answer.",
			Group: "Fixtures", Class: index.Batch}, func(_ struct{}, args []string) (index.Result, error) {
			return index.Result{Requests: []index.Ask{q.Ask(args[0])},
				Then: func(a []any) (index.Result, error) { return index.Result{Text: a[0].(string)}, nil }}, nil
		}))
	f, err := kerntest.New(asker)
	if err != nil {
		t.Fatal(err)
	}
	asked, release := make(chan struct{}), make(chan struct{})
	t.Cleanup(func() { close(release) })
	if err := f.Answer("ask", func(req any) (any, error) { close(asked); <-release; return "late", nil }); err != nil {
		t.Fatal(err)
	}
	call := f.Begin("ask it", nil, "a")
	<-asked
	if !call.Abandon() {
		t.Fatal("giving up the running call answers false")
	}
	if text, err := call.Wait(); !errors.Is(err, host.ErrCallerGaveUp) || text != nil {
		t.Fatalf("the given-up call answers %v, %v, and wants its caller's giving up", text, err)
	}
	if call.Abandon() {
		t.Fatal("a call already given up is given up again")
	}

	seen := make(chan error, 1)
	desk := index.Declare("desk", "Answers.", index.IO(),
		index.Verb("answer", "Waits for its call to end.", func(ctx context.Context, s string) (string, error) {
			<-ctx.Done()
			seen <- context.Cause(ctx)
			return "", ctx.Err()
		}))
	g, err := kerntest.New(desk)
	if err != nil {
		t.Fatal(err)
	}
	served := g.BeginServe("answer", "q")
	served.Gone()
	if _, err := served.Wait(); !errors.Is(err, host.ErrCallerGone) {
		t.Fatalf("the served request whose caller is gone answers %v", err)
	}
	if cause := <-seen; !errors.Is(cause, host.ErrCallerGone) {
		t.Fatalf("the verb's context ends with %v, and wants the gone caller", cause)
	}
	done := g.BeginServe("answer", "q")
	done.Abandon()
	if _, err := done.Wait(); !errors.Is(err, host.ErrCallerGaveUp) {
		t.Fatalf("the served request given up answers %v", err)
	}
	<-seen
	if text, err := f.Call("nothing"); err == nil {
		t.Fatalf("an unknown command answers %v", text)
	}
}
