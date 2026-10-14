// Package indextest is the fake index a module is tested against without the
// index running: the test seeds the inputs and config the module reads, by
// local name, runs a derivation or a command, and reads the outputs it
// committed and the requests it answered, handing each request the answer the
// test gives. It speaks the module contract and nothing more.
package indextest

import (
	"fmt"
	"reflect"
	"slices"

	"github.com/mb-89/SE/src/index"
)

// Fake holds one module's inputs and committed outputs, by local name.
type Fake struct {
	m       *index.Module
	inputs  map[string]index.Port
	outputs map[string]index.Port
	seeded  map[string]any
	out     map[string]any
	answer  map[string]func(any) (any, error)
	asked   []index.Request
}

// New takes a module, and refuses a broken declaration as the index's start would.
func New(m *index.Module) (*Fake, error) {
	if err := m.Err(); err != nil {
		return nil, err
	}
	f := &Fake{m: m, inputs: map[string]index.Port{}, outputs: map[string]index.Port{}, seeded: map[string]any{}, out: map[string]any{}, answer: map[string]func(any) (any, error){}}
	for _, p := range m.Inputs() {
		f.inputs[p.Port] = p
	}
	for _, c := range m.Config() {
		f.seeded[index.ConfigPrefix+c.Port] = c.Builtin
	}
	for _, p := range m.Outputs() {
		f.outputs[p.Port] = p
	}
	return f, nil
}

// Seed sets the value an input port reads; one it never seeds reads its type's zero value.
func (f *Fake) Seed(port string, v any) error {
	p, ok := f.inputs[port]
	switch {
	case !ok:
		return fmt.Errorf("module %s reads no input %q", f.m.Name(), port)
	case !index.Fits(v, p.Type):
		return fmt.Errorf("input %s takes %s, not %T", port, p.Type, v)
	}
	f.seeded[port] = v
	return nil
}

// Config sets a config key's value; one it never sets is the key's built-in value.
func (f *Fake) Config(key string, v any) error { return f.Seed(index.ConfigPrefix+key, v) }

// Derive runs the derivation of an output and commits what it answers.
func (f *Fake) Derive(port string) error {
	v, err := f.m.Derive(port, f.read)
	if err != nil {
		return err
	}
	f.out[port] = v
	return nil
}

// Answer sets what a request through the request port gets: fn's answer,
// or its error, which stops the run as a failed request does on the index.
// A request through a port the test answers nothing fails the run.
func (f *Fake) Answer(port string, fn func(request any) (any, error)) error {
	if !slices.ContainsFunc(f.m.Asks(), func(x index.Exchange) bool { return x.Name == port }) {
		return fmt.Errorf("module %s has no request port %q", f.m.Name(), port)
	}
	f.answer[port] = fn
	return nil
}

// Asked answers every request the module's commands delivered, in order.
func (f *Fake) Asked() []index.Request { return f.asked }

// Serve hands an I/O module's verb a request and answers its answer.
func (f *Fake) Serve(verb string, request any) (any, error) { return f.m.Serve(verb, request) }

// Call runs a command with its arguments, delivers each request it answers to
// the test's answer, commits what it writes, and answers what it shows.
func (f *Fake) Call(name string, args ...string) (string, error) {
	r, err := f.m.Run(name, f.read, args, f.deliver)
	if err != nil {
		return "", err
	}
	for _, w := range r.Writes {
		if w.Gone {
			delete(f.out, at(w.Port, w.Key))
			continue
		}
		f.out[at(w.Port, w.Key)] = w.Value
	}
	return r.Text, nil
}

// Out answers what the module committed to an output, or its built-in value while it committed nothing.
func (f *Fake) Out(port string) (index.Value, error) { return f.OutAt(port, "") }

// OutAt answers what the module committed to a family output at key, or its
// built-in value while it committed nothing there.
func (f *Fake) OutAt(port, key string) (index.Value, error) {
	p, ok := f.outputs[port]
	switch {
	case !ok:
		return index.Value{}, fmt.Errorf("module %s writes no output %q", f.m.Name(), port)
	case p.Family != (key != ""):
		return index.Value{}, fmt.Errorf("output %s of module %s: a family is read at a key, and only a family", port, f.m.Name())
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

func (f *Fake) deliver(port string, request any) (any, error) {
	f.asked = append(f.asked, index.Request{Port: port, Value: request})
	fn, ok := f.answer[port]
	if !ok {
		return nil, fmt.Errorf("the test answers nothing through request port %s", port)
	}
	return fn(request)
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
