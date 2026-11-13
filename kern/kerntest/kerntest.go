// Package kerntest is the fake core a component is tested against without the
// index running: the test seeds the inputs and config the component reads, by
// local name, hands each request port its answers, runs a derivation or a
// command, and reads the outputs it committed and the requests it made. It
// speaks the component contract and nothing more. A call it runs with Begin
// or BeginServe the test gives up as the core does (docs/go-core.md "A call
// given up"): Abandon as call.core.abandon, Gone as the dead-caller check.
package kerntest

import (
	"context"
	"fmt"
	"reflect"
	"strings"
	"sync"

	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// Answerer answers one request on a request port, as the I/O verb the wiring binds it to would.
type Answerer func(req any) (any, error)

// Fake holds one component's inputs, committed outputs and requests, by local
// name. Calls may run side by side, each in its own goroutine, as the core runs them.
type Fake struct {
	mu       sync.Mutex
	c        *index.Component
	inputs   map[string]index.Port
	outputs  map[string]index.Port
	requests map[string]index.RequestDecl
	seeded   map[string]any
	out      map[string]any
	answers  map[string]Answerer
	asked    []index.Ask
	lines    []string
}

// New takes a component, and refuses a broken declaration as the index's start would.
func New(c *index.Component) (*Fake, error) {
	if err := c.Err(); err != nil {
		return nil, err
	}
	f := &Fake{
		c: c, inputs: map[string]index.Port{}, outputs: map[string]index.Port{}, requests: map[string]index.RequestDecl{},
		seeded: map[string]any{}, out: map[string]any{}, answers: map[string]Answerer{},
	}
	for _, p := range c.Inputs() {
		f.inputs[p.Port] = p
	}
	for _, k := range c.Config() {
		f.seeded[index.ConfigPrefix+k.Port] = k.Builtin
	}
	for _, p := range c.Outputs() {
		f.outputs[p.Port] = p
	}
	for _, r := range c.Requests() {
		f.requests[r.Port] = r
	}
	return f, nil
}

// Seed sets the value an input port reads; one it never seeds reads its type's zero value.
func (f *Fake) Seed(port string, v any) error {
	p, ok := f.inputs[port]
	switch {
	case !ok:
		return fmt.Errorf("component %s reads no input %q", f.c.Name(), port)
	case !index.Fits(v, p.Type):
		return fmt.Errorf("input %s takes %s, not %T", port, p.Type, v)
	}
	f.mu.Lock()
	f.seeded[port] = v
	f.mu.Unlock()
	return nil
}

// Config sets a config key's value; one it never sets is the key's built-in value.
func (f *Fake) Config(key string, v any) error { return f.Seed(index.ConfigPrefix+key, v) }

// Answer hands a request port the answerer of every request made on it.
func (f *Fake) Answer(port string, a Answerer) error {
	if _, ok := f.requests[port]; !ok {
		return fmt.Errorf("component %s has no request port %q", f.c.Name(), port)
	}
	f.mu.Lock()
	f.answers[port] = a
	f.mu.Unlock()
	return nil
}

// Derive runs the derivation of an output and commits what it answers.
func (f *Fake) Derive(port string) error {
	v, err := f.c.Derive(port, f.read)
	if err != nil {
		return err
	}
	f.mu.Lock()
	f.out[port] = v
	f.mu.Unlock()
	return nil
}

// Call runs a command with its arguments: it commits what each step writes,
// answers each request with its port's answerer, in order, and hands the
// answers to the continuation, as the core does. A failed answer stops the
// command with its reason. It answers every step's text, one line each.
func (f *Fake) Call(name string, args ...string) (string, error) {
	return f.CallSaying(name, nil, args...)
}

// CallSaying runs a command as Call does, and hands say each line the call
// says, as the core hands its caller the lines of its own call alone.
func (f *Fake) CallSaying(name string, say func(line string), args ...string) (string, error) {
	return f.callContext(context.Background(), name, say, args...)
}

// Running is a call the fake runs in its own goroutine, which the test gives
// up as the core gives a call up: Abandon as call.core.abandon does, Gone as
// the core's dead-caller check does once no connection hears the call's reply.
type Running struct {
	ctx    context.Context
	cancel context.CancelCauseFunc
	done   chan struct{}
	answer any
	err    error
}

// Begin runs a command as CallSaying does, in its own goroutine: between its
// steps, and while one of its requests waits for its answerer, it ends once
// the call is given up, with the cause the core names, as index.CallContext.
func (f *Fake) Begin(name string, say func(line string), args ...string) *Running {
	return begin(func(ctx context.Context) (any, error) { return f.callContext(ctx, name, say, args...) })
}

// BeginServe serves one request on a verb of the component, an I/O
// component's, in its own goroutine, handing the verb the call's context, so
// a verb that waits lets go once the call is given up.
func (f *Fake) BeginServe(verb string, req any) *Running {
	return begin(func(ctx context.Context) (any, error) { return f.c.Serve(ctx, verb, req) })
}

func begin(run func(context.Context) (any, error)) *Running {
	ctx, cancel := context.WithCancelCause(context.Background())
	r := &Running{ctx: ctx, cancel: cancel, done: make(chan struct{})}
	go func() {
		defer close(r.done)
		r.answer, r.err = run(ctx)
		if ctx.Err() != nil { // given up: its answer, or the verb's own error, is dropped
			r.answer, r.err = nil, given(ctx)
		}
	}()
	return r
}

// Abandon gives the call up as call.core.abandon does, with
// host.ErrCallerGaveUp; it answers whether the call still ran, as the core's
// answer does.
func (r *Running) Abandon() bool { return r.end(host.ErrCallerGaveUp) }

// Gone gives the call up as the core's dead-caller check does once its
// caller's connection is gone, with host.ErrCallerGone.
func (r *Running) Gone() { r.end(host.ErrCallerGone) }

func (r *Running) end(cause error) bool {
	select {
	case <-r.done:
		return false
	default:
	}
	if r.ctx.Err() != nil {
		return false
	}
	r.cancel(cause)
	return true
}

// Wait answers the call's answer once it ended: a command's text, a verb's
// answer, or why it was given up, wrapping the cause.
func (r *Running) Wait() (any, error) {
	<-r.done
	if r.err != nil {
		return nil, r.err
	}
	return r.answer, nil
}

// given is the error of a call whose ctx is done, naming its cause, as the
// index names it; nil while it runs.
func given(ctx context.Context) error {
	if ctx.Err() == nil {
		return nil
	}
	return fmt.Errorf("kerntest: the call is given up: %w", context.Cause(ctx))
}

func (f *Fake) callContext(ctx context.Context, name string, say func(line string), args ...string) (string, error) {
	r, err := f.c.RunContext(ctx, name, f.read, args, nil)
	var text []string
	for {
		if err != nil {
			return strings.Join(text, "\n"), err
		}
		f.mu.Lock()
		f.lines = append(f.lines, r.Lines...)
		for _, w := range r.Writes {
			if w.Gone {
				delete(f.out, at(w.Port, w.Key))
				continue
			}
			f.out[at(w.Port, w.Key)] = w.Value
		}
		f.mu.Unlock()
		if say != nil {
			for _, l := range r.Lines {
				say(l)
			}
		}
		if r.Text != "" {
			text = append(text, r.Text)
		}
		answers := make([]any, 0, len(r.Requests))
		for i, a := range r.Requests {
			ans, err := f.answerWithin(ctx, a)
			if err != nil {
				r.Stopped(err.Error())
				return strings.Join(text, "\n"), fmt.Errorf("%s: request %d of %d, on %s, failed: %w", name, i+1, len(r.Requests), a.Port, err)
			}
			f.mu.Lock()
			f.asked = append(f.asked, a)
			f.mu.Unlock()
			answers = append(answers, ans)
		}
		if r.Then == nil {
			return strings.Join(text, "\n"), nil
		}
		if err := given(ctx); err != nil {
			r.Stopped(err.Error())
			return strings.Join(text, "\n"), err
		}
		r, err = r.Then(answers)
	}
}

// answerWithin answers a request with its port's answerer, and stops waiting
// for it once ctx is done, as the core stops waiting for a verb.
func (f *Fake) answerWithin(ctx context.Context, a index.Ask) (any, error) {
	if ctx.Done() == nil {
		return f.answer(a)
	}
	if err := given(ctx); err != nil {
		return nil, err
	}
	type answered struct {
		v   any
		err error
	}
	got := make(chan answered, 1)
	go func() {
		v, err := f.answer(a)
		got <- answered{v, err}
	}()
	select {
	case g := <-got:
		return g.v, g.err
	case <-ctx.Done():
		return nil, given(ctx)
	}
}

func (f *Fake) answer(a index.Ask) (any, error) {
	f.mu.Lock()
	ans, ok := f.answers[a.Port]
	f.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("request port %s has no answer: hand it one with Answer", a.Port)
	}
	v, err := ans(a.Value)
	if err != nil {
		return nil, err
	}
	if want := f.requests[a.Port].Ans; !index.Fits(v, want) {
		return nil, fmt.Errorf("request port %s reads %s, and its answerer gave %T", a.Port, want, v)
	}
	return v, nil
}

// Lines answers the progress lines every command run so far said, in order.
func (f *Fake) Lines() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string{}, f.lines...)
}

// Requests answers the requests the component made and that were answered, in order.
func (f *Fake) Requests() []index.Ask {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]index.Ask{}, f.asked...)
}

// Out answers what the component committed to an output, or its built-in value while it committed nothing.
func (f *Fake) Out(port string) (index.Value, error) { return f.OutAt(port, "") }

// OutAt answers what the component committed to a family output at key, or its
// built-in value while it committed nothing there.
func (f *Fake) OutAt(port, key string) (index.Value, error) {
	p, ok := f.outputs[port]
	switch {
	case !ok:
		return index.Value{}, fmt.Errorf("component %s writes no output %q", f.c.Name(), port)
	case p.Family != (key != ""):
		return index.Value{}, fmt.Errorf("output %s of component %s: a family is read at a key, and only a family", port, f.c.Name())
	}
	f.mu.Lock()
	v, ok := f.out[at(port, key)]
	f.mu.Unlock()
	if ok {
		return index.Value{V: v, Provided: true}, nil
	}
	return index.Value{V: p.Builtin}, nil
}

// at is where a write to port at key stands among the fake's outputs.
func at(port, key string) string {
	if key == "" {
		return port
	}
	return port + "/" + key
}

func (f *Fake) read(port string) any {
	f.mu.Lock()
	v, ok := f.seeded[port]
	f.mu.Unlock()
	if ok {
		return v
	}
	if p, ok := f.inputs[port]; ok {
		return reflect.Zero(p.Type).Interface()
	}
	return nil
}
