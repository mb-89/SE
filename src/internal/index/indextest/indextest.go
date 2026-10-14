// Package indextest is the fake index a module is tested against without the
// index running: the test seeds the inputs and config the module reads, by
// local name, runs a derivation or a command, and reads the outputs it
// committed. It speaks the module contract and nothing more.
package indextest

import (
	"fmt"
	"reflect"

	"github.com/mb-89/SE/src/internal/index"
)

// Fake holds one module's inputs and committed outputs, by local name.
type Fake struct {
	m       *index.Module
	inputs  map[string]index.Port
	outputs map[string]index.Port
	seeded  map[string]any
	out     map[string]any
}

// New takes a module, and refuses a broken declaration as the index's start would.
func New(m *index.Module) (*Fake, error) {
	if err := m.Err(); err != nil {
		return nil, err
	}
	f := &Fake{m: m, inputs: map[string]index.Port{}, outputs: map[string]index.Port{}, seeded: map[string]any{}, out: map[string]any{}}
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

// Call runs a command with its arguments, commits what it writes, and answers what it shows.
func (f *Fake) Call(name string, args ...string) (string, error) {
	r, err := f.m.Run(name, f.read, args)
	if err != nil {
		return "", err
	}
	for _, w := range r.Writes {
		f.out[w.Port] = w.Value
	}
	return r.Text, nil
}

// Out answers what the module committed to an output, or its built-in value while it committed nothing.
func (f *Fake) Out(port string) (index.Value, error) {
	p, ok := f.outputs[port]
	if !ok {
		return index.Value{}, fmt.Errorf("module %s writes no output %q", f.m.Name(), port)
	}
	if v, ok := f.out[port]; ok {
		return index.Value{V: v, Provided: true}, nil
	}
	return index.Value{V: p.Builtin}, nil
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
