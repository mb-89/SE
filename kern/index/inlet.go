package index

import (
	"errors"
	"fmt"
)

// Commit is an instance's own commit: an I/O component writes what comes in
// from its outside thing with it, held to its declaration as Index.Commit is.
type Commit func(writes ...Write) error

type inletPart struct {
	fn func(instance string, read Reader, commit Commit) error
}

func (p inletPart) declare(c *Component) {
	if c.inlet != nil {
		c.fail("component %s declares two inlets", c.name)
	}
	c.inlet = p.fn
}

// Inlet declares that an I/O component writes what comes in from its outside
// thing on its own, not only from its commands: the start hands fn each
// switched-on instance's name, a reader of its config, and its commit. An
// error refuses the start.
func Inlet(fn func(instance string, read Reader, commit Commit) error) Part { return inletPart{fn} }

type hearsPart struct {
	fn func(instance, event string, payload []byte) error
}

func (p hearsPart) declare(c *Component) {
	if c.hears != nil {
		c.fail("component %s hears the host's events twice", c.name)
	}
	c.hears = p.fn
}

// Hears declares that an I/O component hears the host's events: each event
// the core is handed, such as a session's PostToolUse, with its payload as the
// host gave it. Its outside thing is what the host reports.
func Hears(fn func(instance, event string, payload []byte) error) Part { return hearsPart{fn} }

// inlets hands each switched-on instance whose component declares an inlet its commit.
func (ix *Index) inlets() error {
	var errs []error
	for _, in := range ix.order {
		if !in.enabled || in.comp.inlet == nil {
			continue
		}
		in := in
		commit := func(writes ...Write) error { return ix.Commit(in.name, writes...) }
		if err := in.comp.inlet(in.name, in.reader(ix.Snapshot(), ""), commit); err != nil {
			errs = append(errs, fmt.Errorf("index: instance %s (wiring line %d): %w", in.name, in.line, err))
		}
	}
	return errors.Join(errs...)
}

// Hear hands a host's event to every switched-on instance whose component
// hears them, in the instances' order, and answers what each refused. A
// switched-off instance hears nothing.
func (ix *Index) Hear(event string, payload []byte) error {
	var errs []error
	for _, in := range ix.order {
		if !in.enabled || in.comp.hears == nil {
			continue
		}
		if err := in.comp.hears(in.name, event, payload); err != nil {
			errs = append(errs, fmt.Errorf("index: instance %s hears %s: %w", in.name, event, err))
		}
	}
	return errors.Join(errs...)
}
