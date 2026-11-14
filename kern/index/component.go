// Package index is kern's index: it keeps names and their single writers, the
// store and its snapshots, pushes changes in waves, answers built-in values,
// delivers a command's requests to I/O components, checks the catalog the
// wiring makes at start, and gathers what the components declare into the
// catalog every surface renders. It holds no business logic, touches no
// outside thing but its wiring file, and no line of it names a component.
// SE's docs/go-core.md is its design until kern has a repository of its own.
package index

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"sort"
	"strings"
)

// ConfigPrefix starts the local port a component reads a config key by:
// config/<key>, under <instance>/config/<key> in the store.
const ConfigPrefix = "config/"

// Part is one thing a component declares: an output, a derivation, a config
// key, a command, a request port, a verb or the I/O flag.
type Part interface{ declare(c *Component) }

// Port is one declared port as the catalog and the fake core see it.
type Port struct {
	// Port is the local name the component knows it by.
	Port string
	// Type is the Go type of its value.
	Type reflect.Type
	// Builtin is the value read while nothing is provided; an input's is its type's zero value.
	Builtin any
	// Help is its one help line; an input has none.
	Help string
	// Derived is set on an output a derivation writes rather than a command.
	Derived bool
	// Family is set on an output written at a key: the wiring binds it to a
	// family, a name with one key segment, and each write names its key.
	Family bool
	// Shape is the named JSON shape a declared port carries, such as
	// github.issues, whose Go type is any; a wire joins only equal shapes.
	Shape string
}

// Write is one value a run commits to one of its component's outputs.
type Write struct {
	Port  string
	Value any
	// Key is the key a write to a family output stands at; a plain output's has none.
	Key string
	// Gone drops the key from the family: its name reads the built-in value again.
	Gone bool
}

// Ask is one request a command answers, on one of its component's local
// request ports. The wiring binds the port to an I/O component's verb.
type Ask struct {
	Port  string
	Value any
}

// Result is what a command, or one of its continuations, answers: what to
// show, what it commits, and the requests going out. The core commits the
// writes, then delivers the requests in order; a failed request stops the
// list and the command fails with its reason, and nothing is undone. Then,
// where set, reads the answers in the order of Requests and answers the next
// step.
type Result struct {
	Text string
	// Lines are the progress lines the step said before its text, such as "Phase: reading".
	Lines []string
	// Said is set where every line was already handed to the call's say,
	// live, as a declared component's process said it.
	Said     bool
	Writes   []Write
	Requests []Ask
	Then     func(answers []any) (Result, error)
	// Stop, where set beside Then, tells the component that its call is given
	// up and Then never runs: a declared component's process ends what waits
	// on it (docs/go-core.md "A call given up").
	Stop func(reason string)
}

// CommandDecl is a command as a component declares it, and as every surface renders it.
type CommandDecl struct {
	// Name is the words that call it: "fleet-check".
	Name string
	// Usage is the command line, the name first, with its flags.
	Usage string
	// Summary is one short line, no flags.
	Summary string
	// Help is what its help says beyond the usage.
	Help string
	// Group is the heading it stands under in the help listing.
	Group string
	// Session offers it to the agent as a command.
	Session bool
	// Class is Interactive or Batch: whether a person waits on its answer.
	Class Class
	// MCP is what an agent host reads of it as a tool of kern's MCP door
	// (package mcp): when to use it. An interactive command, which only
	// reads, is offered there and must carry one; a batch command is not.
	MCP string
}

// Class says who waits on a command.
type Class string

const (
	// Interactive is a command a person waits on: its first line within 1 s.
	Interactive Class = "interactive"
	// Batch is a command that must write, or that a hook, CI or another
	// command runs: it goes out at once.
	Batch Class = "batch"
)

// RequestDecl is a local request port: the request it sends and the answer it reads.
type RequestDecl struct {
	Port     string
	Req, Ans reflect.Type
	Help     string
	// ReqShape and AnsShape are the named JSON shapes of a declared port's request and answer.
	ReqShape, AnsShape string
}

// VerbDecl is a verb an I/O component accepts: the request it takes and the answer it gives.
type VerbDecl struct {
	Verb     string
	Req, Ans reflect.Type
	Help     string
	// ReqShape and AnsShape are the named JSON shapes of a declared verb's request and answer.
	ReqShape, AnsShape string
}

// Reader answers the value of a local input port.
type Reader func(port string) any

// Component is one component's declaration: its ports, config, commands,
// request ports and verbs, by local name only. Declare makes one; its methods
// are the component contract the core and the fake core both speak.
type Component struct {
	name, help string
	io         bool
	inputs     map[string]reflect.Type
	outputs    map[string]*Port
	config     map[string]*Port
	derive     map[string]*derivation
	commands   map[string]*command
	requests   map[string]*RequestDecl
	verbs      map[string]*verb
	errs       []string
	// decl is set on a component declared by its component.toml alone: its
	// derivations, commands and verbs run in its own process, over the bus.
	decl *declared
	// inlet and hears are an I/O component's own commit and its ear for the host's events.
	inlet func(instance string, read Reader, commit Commit) error
	hears func(instance, event string, payload []byte) error
	// tells is an I/O component's word to the agent on the host's events.
	tells func(instance, event string, payload []byte) string
}

type derivation struct {
	in  inputStruct
	run func(reflect.Value) (any, error)
}

type command struct {
	decl CommandDecl
	in   inputStruct
	run  func(reflect.Value, []string) (Result, error)
}

type verb struct {
	decl  VerbDecl
	serve func(context.Context, any) (any, error)
}

// inputStruct is a run's input struct: its type, and the local port each field reads.
type inputStruct struct {
	typ   reflect.Type
	ports []string
}

// Declare makes a component from its parts. A broken declaration is kept and
// refused when the index starts or a fake takes the component.
func Declare(name, help string, parts ...Part) *Component {
	c := &Component{
		name: name, help: help,
		inputs:   map[string]reflect.Type{},
		outputs:  map[string]*Port{},
		config:   map[string]*Port{},
		derive:   map[string]*derivation{},
		commands: map[string]*command{},
		requests: map[string]*RequestDecl{},
		verbs:    map[string]*verb{},
	}
	if !pathName(name) {
		c.fail("a component needs a name of letters, digits and dashes, or <group>/<component>, not %q", name)
	}
	if strings.TrimSpace(help) == "" {
		c.fail("component %s has no help", name)
	}
	for _, p := range parts {
		p.declare(c)
	}
	for port, t := range c.inputs {
		if key, ok := strings.CutPrefix(port, ConfigPrefix); ok {
			k, declared := c.config[key]
			switch {
			case !declared:
				c.fail("input %s reads config key %s, which is not declared", port, key)
			case k.Type != t:
				c.fail("input %s is %s, but config key %s is %s", port, t, key, k.Type)
			}
			continue
		}
		if _, taken := c.outputs[port]; taken {
			c.fail("port %s is both an input and an output", port)
		}
	}
	for port := range c.requests {
		_, isIn := c.inputs[port]
		_, isOut := c.outputs[port]
		if isIn || isOut {
			c.fail("request port %s is also an input or an output", port)
		}
	}
	if len(c.verbs) > 0 && !c.io {
		c.fail("component %s accepts verbs but carries no I/O flag: only an I/O component reaches the outside", name)
	}
	if (c.inlet != nil || c.hears != nil || c.tells != nil) && !c.io {
		c.fail("component %s commits on its own or hears the host's events but carries no I/O flag", name)
	}
	return c
}

func (c *Component) fail(format string, a ...any) {
	c.errs = append(c.errs, fmt.Sprintf(format, a...))
}

// Name is the component's name, which the wiring file's instances name.
func (c *Component) Name() string { return c.name }

// IO says whether the component carries the I/O flag: it touches its one outside thing.
func (c *Component) IO() bool { return c.io }

// Help is the component's one help line.
func (c *Component) Help() string { return c.help }

// Err is what is wrong with the declaration, or nil.
func (c *Component) Err() error {
	if len(c.errs) == 0 {
		return nil
	}
	return errors.New("component " + c.name + ": " + strings.Join(c.errs, "; "))
}

// Inputs are the ports the component reads, config ones among them, by local name.
func (c *Component) Inputs() []Port {
	var out []Port
	for _, p := range sortedKeys(c.inputs) {
		port := Port{Port: p, Type: c.inputs[p], Builtin: reflect.Zero(c.inputs[p]).Interface()}
		if c.decl != nil {
			port.Shape = c.decl.inShapes[p]
		}
		out = append(out, port)
	}
	return out
}

// Outputs are the ports the component writes.
func (c *Component) Outputs() []Port { return ports(c.outputs) }

// Config are the component's config keys; Port is the key.
func (c *Component) Config() []Port { return ports(c.config) }

// Commands are the commands the component declares, by name.
func (c *Component) Commands() []CommandDecl {
	var out []CommandDecl
	for _, n := range sortedKeys(c.commands) {
		out = append(out, c.commands[n].decl)
	}
	return out
}

// Requests are the component's local request ports.
func (c *Component) Requests() []RequestDecl {
	var out []RequestDecl
	for _, n := range sortedKeys(c.requests) {
		out = append(out, *c.requests[n])
	}
	return out
}

// Verbs are the verbs the component accepts, an I/O component's alone.
func (c *Component) Verbs() []VerbDecl {
	var out []VerbDecl
	for _, n := range sortedKeys(c.verbs) {
		out = append(out, c.verbs[n].decl)
	}
	return out
}

// Derivations are the outputs a derivation writes.
func (c *Component) Derivations() []string { return sortedKeys(c.derive) }

// ReadsOf answers the local input ports the derivation of output, or the command, reads.
func (c *Component) ReadsOf(name string) []string {
	if d, ok := c.derive[name]; ok {
		return d.in.ports
	}
	if k, ok := c.commands[name]; ok {
		return k.in.ports
	}
	return nil
}

// Derive runs the derivation of output port on what read answers.
func (c *Component) Derive(port string, read Reader) (any, error) {
	d, ok := c.derive[port]
	if !ok {
		return nil, fmt.Errorf("component %s derives no output %q", c.name, port)
	}
	if c.decl != nil {
		return nil, fmt.Errorf("component %s derives %s in its own process, which commits it", c.name, port)
	}
	in, err := d.in.fill(read)
	if err != nil {
		return nil, err
	}
	return d.run(in)
}

// Run runs the command name with its arguments on what read answers. It
// refuses a result, or a continuation's, that writes a port the component's
// commands do not write or asks on a port it does not declare.
func (c *Component) Run(name string, read Reader, args []string) (Result, error) {
	return c.RunSaying(name, read, args, nil)
}

// RunSaying runs a command's first step as Run does; say, where set, takes
// each progress line a declared component's process says, as it says it.
func (c *Component) RunSaying(name string, read Reader, args []string, say func(string)) (Result, error) {
	return c.RunContext(context.Background(), name, read, args, say)
}

// RunContext runs a command's first step as RunSaying does, within ctx: a
// declared component's step, and each of its continuations, ends once ctx is
// done, and its process is told the call is given up.
func (c *Component) RunContext(ctx context.Context, name string, read Reader, args []string, say func(string)) (Result, error) {
	k, ok := c.commands[name]
	if !ok {
		return Result{}, fmt.Errorf("component %s has no command %q", c.name, name)
	}
	if c.decl != nil {
		return c.checked(c.runRemote(ctx, name, read, args, say))
	}
	in, err := k.in.fill(read)
	if err != nil {
		return Result{}, err
	}
	return c.checked(k.run(in, args))
}

// checked refuses a result that breaks the contract, and holds its continuation to the same.
func (c *Component) checked(r Result, err error) (Result, error) {
	if err != nil {
		return Result{}, err
	}
	err = c.CheckWrites(r.Writes)
	if err == nil {
		err = c.CheckAsks(r.Requests)
	}
	if err != nil {
		r.Stopped(err.Error())
		return Result{}, err
	}
	if then := r.Then; then != nil {
		r.Then = func(answers []any) (Result, error) { return c.checked(then(answers)) }
	}
	return r, nil
}

// Stopped tells the component that the call this result belongs to is given
// up, where a continuation of it waits and the component asked to be told.
func (r Result) Stopped(reason string) {
	if r.Then != nil && r.Stop != nil {
		r.Stop(reason)
	}
}

// CheckWrites refuses a write to anything but one of the component's outputs
// a command writes, or of another type than the port's.
func (c *Component) CheckWrites(writes []Write) error { return c.checkWrites(writes, false) }

// checkWrites is CheckWrites; derived lets a declared component's own process
// commit what its derivations answer.
func (c *Component) checkWrites(writes []Write, derived bool) error {
	for _, w := range writes {
		o, ok := c.outputs[w.Port]
		switch {
		case !ok:
			return fmt.Errorf("component %s writes no output %q", c.name, w.Port)
		case o.Derived && !derived:
			return fmt.Errorf("component %s: output %s is written by its derivation alone", c.name, w.Port)
		case w.Gone && !o.Family:
			return fmt.Errorf("component %s: output %s is no family, and drops no key", c.name, w.Port)
		case !w.Gone && !Fits(w.Value, o.Type):
			return fmt.Errorf("component %s: output %s takes %s, not %T", c.name, w.Port, o.Type, w.Value)
		case o.Family && !Key(w.Key):
			return fmt.Errorf("component %s: output %s is a family, and %q is no key: letters, digits, dots, dashes and underscores", c.name, w.Port, w.Key)
		case !o.Family && w.Key != "":
			return fmt.Errorf("component %s: output %s is no family, and takes no key", c.name, w.Port)
		}
	}
	return nil
}

// CheckAsks refuses a request on a port the component does not declare, or of another type than the port's.
func (c *Component) CheckAsks(asks []Ask) error {
	for _, a := range asks {
		r, ok := c.requests[a.Port]
		switch {
		case !ok:
			return fmt.Errorf("component %s has no request port %q", c.name, a.Port)
		case !Fits(a.Value, r.Req):
			return fmt.Errorf("component %s: request port %s sends %s, not %T", c.name, a.Port, r.Req, a.Value)
		}
	}
	return nil
}

// Serve answers one request on a verb, as the I/O component's outside thing
// answers it, until ctx is done: the call that asked it is given up, so the
// verb lets go of what it holds for it (docs/go-core.md "A call given up").
func (c *Component) Serve(ctx context.Context, name string, req any) (any, error) {
	v, ok := c.verbs[name]
	switch {
	case !ok:
		return nil, fmt.Errorf("component %s accepts no verb %q", c.name, name)
	case !Fits(req, v.decl.Req):
		return nil, fmt.Errorf("component %s: verb %s takes %s, not %T", c.name, name, v.decl.Req, req)
	}
	if c.decl != nil {
		return c.serveRemote(ctx, v.decl, req)
	}
	return v.serve(ctx, req)
}

// OutPort is an output a command writes; Set makes the write.
type OutPort[T any] struct{ port Port }

// Output declares an output port that the component's commands write, with
// its built-in value and its help line.
func Output[T any](port string, builtin T, help string) *OutPort[T] {
	return &OutPort[T]{Port{Port: port, Type: reflect.TypeFor[T](), Builtin: builtin, Help: help}}
}

// Set is a write of v to the port.
func (o *OutPort[T]) Set(v T) Write { return Write{Port: o.port.Port, Value: v} }

func (o *OutPort[T]) declare(c *Component) { c.addOutput(o.port) }

func (c *Component) addOutput(p Port) {
	if !portName(p.Port) {
		c.fail("output %q needs a local name of letters, digits and dashes", p.Port)
	}
	if _, taken := c.outputs[p.Port]; taken {
		c.fail("output %s is declared twice", p.Port)
	}
	if strings.TrimSpace(p.Help) == "" {
		c.fail("output %s has no help", p.Port)
	}
	c.outputs[p.Port] = &p
}

// FamilyPort is a family output a command writes: each write stands at a key,
// such as a session's id. At makes the write.
type FamilyPort[T any] struct{ port Port }

// Family declares an output port written at keys, with the built-in value
// every key reads while nothing stands at it, and its help line. The wiring
// binds it to a family, a name with one key segment such as session/<id>/events;
// keys come and go inside it, and no name is added at runtime.
func Family[T any](port string, builtin T, help string) *FamilyPort[T] {
	return &FamilyPort[T]{Port{Port: port, Type: reflect.TypeFor[T](), Builtin: builtin, Help: help, Family: true}}
}

// At is a write of v at key.
func (o *FamilyPort[T]) At(key string, v T) Write {
	return Write{Port: o.port.Port, Value: v, Key: key}
}

// Drop is a write that takes key out of the family.
func (o *FamilyPort[T]) Drop(key string) Write { return Write{Port: o.port.Port, Key: key, Gone: true} }

func (o *FamilyPort[T]) declare(c *Component) { c.addOutput(o.port) }

type derivedPart struct {
	port Port
	d    *derivation
	err  error
}

func (p derivedPart) declare(c *Component) {
	c.addOutput(p.port)
	if p.err != nil {
		c.fail("derivation %s: %v", p.port.Port, p.err)
		return
	}
	c.addInputs(p.d.in)
	c.derive[p.port.Port] = p.d
}

// Derived declares an output port fn computes from the input struct In, with
// its built-in value and help line. The index runs fn whenever a name In reads
// changes.
func Derived[In, Out any](port string, builtin Out, help string, fn func(In) (Out, error)) Part {
	in, err := inputsOf(reflect.TypeFor[In]())
	return derivedPart{
		port: Port{Port: port, Type: reflect.TypeFor[Out](), Builtin: builtin, Help: help, Derived: true},
		d: &derivation{in: in, run: func(v reflect.Value) (any, error) {
			return fn(v.Interface().(In))
		}},
		err: err,
	}
}

type ioPart struct{}

func (ioPart) declare(c *Component) { c.io = true }

// IO is the I/O flag: the component touches its one outside thing. A
// component without it is a compute component.
func IO() Part { return ioPart{} }

type configPart struct{ port Port }

// Config declares a config key with its built-in value and help line. A run
// reads it as the input port config/<key>.
func Config[T any](key string, builtin T, help string) Part {
	return configPart{Port{Port: key, Type: reflect.TypeFor[T](), Builtin: builtin, Help: help}}
}

func (p configPart) declare(c *Component) { c.addConfig(p.port) }

func (c *Component) addConfig(p Port) {
	if !portName(p.Port) {
		c.fail("config key %q needs a local name of letters, digits and dashes", p.Port)
	}
	if _, taken := c.config[p.Port]; taken {
		c.fail("config key %s is declared twice", p.Port)
	}
	if strings.TrimSpace(p.Help) == "" {
		c.fail("config key %s has no help", p.Port)
	}
	c.config[p.Port] = &p
}

// RequestPort is a local request port a command asks on; Ask makes the
// request and Answer reads its answer.
type RequestPort[Req, Ans any] struct{ decl RequestDecl }

// Request declares a local request port, with its help line. The wiring binds
// it to an I/O component's verb that takes Req and answers Ans.
func Request[Req, Ans any](port, help string) *RequestPort[Req, Ans] {
	return &RequestPort[Req, Ans]{RequestDecl{Port: port, Req: reflect.TypeFor[Req](), Ans: reflect.TypeFor[Ans](), Help: help}}
}

// Ask is a request of v on the port.
func (r *RequestPort[Req, Ans]) Ask(v Req) Ask { return Ask{Port: r.decl.Port, Value: v} }

// Answer reads the answer to a request on the port, as a continuation is handed it.
func (r *RequestPort[Req, Ans]) Answer(a any) Ans {
	v, _ := a.(Ans)
	return v
}

func (r *RequestPort[Req, Ans]) declare(c *Component) { c.addRequest(r.decl) }

func (c *Component) addRequest(p RequestDecl) {
	if !portName(p.Port) {
		c.fail("request port %q needs a local name of letters, digits and dashes", p.Port)
	}
	if _, taken := c.requests[p.Port]; taken {
		c.fail("request port %s is declared twice", p.Port)
	}
	if strings.TrimSpace(p.Help) == "" {
		c.fail("request port %s has no help", p.Port)
	}
	c.requests[p.Port] = &p
}

type verbPart struct{ v *verb }

// Verb declares a verb the I/O component accepts from others, with its help
// line: fn reaches the component's outside thing and answers the request. Its
// ctx is done once the call that asked it is given up; a verb that waits on
// something outside lets go of it then.
func Verb[Req, Ans any](name, help string, fn func(context.Context, Req) (Ans, error)) Part {
	return verbPart{&verb{
		decl: VerbDecl{Verb: name, Req: reflect.TypeFor[Req](), Ans: reflect.TypeFor[Ans](), Help: help},
		serve: func(ctx context.Context, req any) (any, error) {
			r, _ := req.(Req)
			return fn(ctx, r)
		},
	}}
}

func (p verbPart) declare(c *Component) { c.addVerb(p.v) }

func (c *Component) addVerb(v *verb) {
	d := v.decl
	if !portName(d.Verb) {
		c.fail("verb %q needs a local name of letters, digits and dashes", d.Verb)
	}
	if _, taken := c.verbs[d.Verb]; taken {
		c.fail("verb %s is declared twice", d.Verb)
	}
	if strings.TrimSpace(d.Help) == "" {
		c.fail("verb %s has no help", d.Verb)
	}
	c.verbs[d.Verb] = v
}

type commandPart struct {
	c   *command
	err error
}

// Command declares a command: fn reads the input struct In and the command's
// arguments, and answers what to show, what to commit and the requests going out.
func Command[In any](decl CommandDecl, fn func(in In, args []string) (Result, error)) Part {
	in, err := inputsOf(reflect.TypeFor[In]())
	return commandPart{c: &command{decl: decl, in: in, run: func(v reflect.Value, args []string) (Result, error) {
		return fn(v.Interface().(In), args)
	}}, err: err}
}

func (p commandPart) declare(c *Component) {
	if p.err != nil {
		c.fail("command %q: %v", p.c.decl.Name, p.err)
		return
	}
	c.addCommand(p.c)
}

func (c *Component) addCommand(k *command) {
	d := k.decl
	for _, f := range []struct{ field, v string }{{"name", d.Name}, {"usage", d.Usage}, {"summary", d.Summary}, {"help", d.Help}, {"group", d.Group}} {
		if strings.TrimSpace(f.v) == "" {
			c.fail("command %q has no %s", d.Name, f.field)
		}
	}
	if d.Class != Interactive && d.Class != Batch {
		c.fail("command %q has no class: %s or %s", d.Name, Interactive, Batch)
	}
	if d.Class == Interactive && strings.TrimSpace(d.MCP) == "" {
		c.fail("command %q is interactive and has no mcp description: the MCP door offers it, and says when to use it", d.Name)
	}
	if _, taken := c.commands[d.Name]; taken {
		c.fail("command %q is declared twice", d.Name)
	}
	c.addInputs(k.in)
	c.commands[d.Name] = k
}

func (c *Component) addInputs(in inputStruct) {
	if in.typ == nil {
		return // a declared component's inputs stand in its declaration
	}
	for i, port := range in.ports {
		t := in.typ.Field(i).Type
		if have, ok := c.inputs[port]; ok && have != t {
			c.fail("input %s is read as %s and as %s", port, have, t)
		}
		c.inputs[port] = t
	}
}

// inputsOf reads an input struct: every field is a port, tagged index:"<port>".
func inputsOf(t reflect.Type) (inputStruct, error) {
	if t.Kind() != reflect.Struct {
		return inputStruct{}, fmt.Errorf("the input %s is no struct", t)
	}
	in := inputStruct{typ: t}
	for i := range t.NumField() {
		f := t.Field(i)
		port := f.Tag.Get("index")
		valid := portName(port)
		if key, isConfig := strings.CutPrefix(port, ConfigPrefix); isConfig {
			valid = portName(key)
		}
		if !f.IsExported() || !valid {
			return inputStruct{}, fmt.Errorf("field %s of %s needs to be exported and tagged index:\"<port>\"", f.Name, t)
		}
		in.ports = append(in.ports, port)
	}
	return in, nil
}

// fill makes the input struct from what read answers for each port.
func (in inputStruct) fill(read Reader) (reflect.Value, error) {
	v := reflect.New(in.typ).Elem()
	for i, port := range in.ports {
		x := read(port)
		if x == nil {
			continue
		}
		f := v.Field(i)
		xv := reflect.ValueOf(x)
		if !xv.Type().AssignableTo(f.Type()) {
			return v, fmt.Errorf("input %s takes %s, not %s", port, f.Type(), xv.Type())
		}
		f.Set(xv)
	}
	return v, nil
}

// Fits says whether v can stand in a port of type t.
func Fits(v any, t reflect.Type) bool {
	if v == nil {
		switch t.Kind() {
		case reflect.Interface, reflect.Pointer, reflect.Slice, reflect.Map:
			return true
		}
		return false
	}
	return reflect.TypeOf(v).AssignableTo(t)
}

// Key says whether s can be a key in a family: letters, digits, dots, dashes
// and underscores, and neither "." nor "..".
func Key(s string) bool {
	if s == "" || s == "." || s == ".." {
		return false
	}
	for _, r := range s {
		switch {
		case r == '-', r == '.', r == '_', r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		default:
			return false
		}
	}
	return true
}

// pathName says whether s is a component's or an instance's name: segments of
// letters, digits and dashes, split by /, such as tally or issues/pull. A
// nested instance owns the names under it.
func pathName(s string) bool {
	for _, seg := range strings.Split(s, "/") {
		if !portName(seg) {
			return false
		}
	}
	return true
}

// portName says whether s is a local name: letters, digits and dashes.
func portName(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		switch {
		case r == '-', r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
		default:
			return false
		}
	}
	return true
}

func ports(m map[string]*Port) []Port {
	var out []Port
	for _, k := range sortedKeys(m) {
		out = append(out, *m[k])
	}
	return out
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// JSONVerb declares a verb whose request and answer ride as the named JSON
// shapes reqShape and ansShape, so a component in another language, which
// asks in JSON, binds to it: fn is handed the request decoded into Req, and
// its answer rides as JSON. Its ctx is Verb's.
func JSONVerb[Req, Ans any](name, help, reqShape, ansShape string, fn func(context.Context, Req) (Ans, error)) Part {
	anyType := reflect.TypeFor[any]()
	return verbPart{&verb{
		decl: VerbDecl{Verb: name, Req: anyType, Ans: anyType, Help: help, ReqShape: reqShape, AnsShape: ansShape},
		serve: func(ctx context.Context, req any) (any, error) {
			var r Req
			if err := Recode(req, &r); err != nil {
				return nil, fmt.Errorf("verb %s takes %s: %w", name, reqShape, err)
			}
			a, err := fn(ctx, r)
			if err != nil {
				return nil, err
			}
			var out any
			return out, Recode(a, &out)
		},
	}}
}

// JSONRequest declares a request port of the named JSON shapes reqShape and
// ansShape, which the wiring binds to a JSONVerb or a declared verb of those
// shapes; Answer reads its answer as JSON, which Recode decodes.
func JSONRequest(port, help, reqShape, ansShape string) *RequestPort[any, any] {
	anyType := reflect.TypeFor[any]()
	return &RequestPort[any, any]{RequestDecl{Port: port, Req: anyType, Ans: anyType, Help: help, ReqShape: reqShape, AnsShape: ansShape}}
}

// Recode decodes v into out by way of JSON: a shape's value into its Go type.
func Recode(v any, out any) error {
	data, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, out)
}
