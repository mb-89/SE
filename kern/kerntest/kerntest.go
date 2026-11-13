// Package kerntest is the fake core a component is tested against without the
// index running: the test seeds the inputs and config the component reads, by
// local name, hands each request port its answers, runs a derivation or a
// command, and reads the outputs it committed and the requests it made. It
// speaks the component contract and nothing more.
package kerntest

import (
	"fmt"
	"reflect"
	"strings"

	"github.com/mb-89/kern/index"
)

// Answerer answers one request on a request port, as the I/O verb the wiring binds it to would.
type Answerer func(req any) (any, error)

// Fake holds one component's inputs, committed outputs and requests, by local name.
type Fake struct {
	c        *index.Component
	inputs   map[string]index.Port
	outputs  map[string]index.Port
	requests map[string]index.RequestDecl
	seeded   map[string]any
	out      map[string]any
	answers  map[string]Answerer
	asked    []index.Ask
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
	f.seeded[port] = v
	return nil
}

// Config sets a config key's value; one it never sets is the key's built-in value.
func (f *Fake) Config(key string, v any) error { return f.Seed(index.ConfigPrefix+key, v) }

// Answer hands a request port the answerer of every request made on it.
func (f *Fake) Answer(port string, a Answerer) error {
	if _, ok := f.requests[port]; !ok {
		return fmt.Errorf("component %s has no request port %q", f.c.Name(), port)
	}
	f.answers[port] = a
	return nil
}

// Derive runs the derivation of an output and commits what it answers.
func (f *Fake) Derive(port string) error {
	v, err := f.c.Derive(port, f.read)
	if err != nil {
		return err
	}
	f.out[port] = v
	return nil
}

// Call runs a command with its arguments: it commits what each step writes,
// answers each request with its port's answerer, in order, and hands the
// answers to the continuation, as the core does. A failed answer stops the
// command with its reason. It answers every step's text, one line each.
func (f *Fake) Call(name string, args ...string) (string, error) {
	r, err := f.c.Run(name, f.read, args)
	var text []string
	for {
		if err != nil {
			return strings.Join(text, "\n"), err
		}
		if r.Text != "" {
			text = append(text, r.Text)
		}
		for _, w := range r.Writes {
			if w.Gone {
				delete(f.out, at(w.Port, w.Key))
				continue
			}
			f.out[at(w.Port, w.Key)] = w.Value
		}
		answers := make([]any, 0, len(r.Requests))
		for i, a := range r.Requests {
			ans, err := f.answer(a)
			if err != nil {
				return strings.Join(text, "\n"), fmt.Errorf("%s: request %d of %d, on %s, failed: %w", name, i+1, len(r.Requests), a.Port, err)
			}
			f.asked = append(f.asked, a)
			answers = append(answers, ans)
		}
		if r.Then == nil {
			return strings.Join(text, "\n"), nil
		}
		r, err = r.Then(answers)
	}
}

func (f *Fake) answer(a index.Ask) (any, error) {
	ans, ok := f.answers[a.Port]
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

// Requests answers the requests the component made and that were answered, in order.
func (f *Fake) Requests() []index.Ask { return append([]index.Ask{}, f.asked...) }

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
	if v, ok := f.out[at(port, key)]; ok {
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
	if v, ok := f.seeded[port]; ok {
		return v
	}
	if p, ok := f.inputs[port]; ok {
		return reflect.Zero(p.Type).Interface()
	}
	return nil
}
