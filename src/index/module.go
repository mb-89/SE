// Package index is SE's index core: it keeps names and their single writers,
// the store and its snapshots, pushes changes, answers built-in values, starts
// the modules the wiring file names, and gathers what they declare into the
// catalog every adapter renders. It holds no business logic, touches no
// outside thing, and no line of it names a module. spec/index.md is its design.
package index

import (
	"errors"
	"fmt"
	"reflect"
	"sort"
	"strings"
)

// ConfigPrefix starts the local port a module reads a config key by:
// config/<key>, under <instance>/config/<key> in the store.
const ConfigPrefix = "config/"

// Part is one thing a module declares: an output, a derivation, a config key,
// a command, a request port or a verb. Output, Derived, Config, Command, Ask
// and Verb make them.
type Part interface{ declare(m *Module) }

// Port is one declared port as the catalog and the fake index see it.
type Port struct {
	// Port is the local name the module knows it by.
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
}

// Write is one value a run commits to one of its module's outputs.
type Write struct {
	Port  string
	Value any
	// Key is the key a write to a family output stands at; a plain output's has none.
	Key string
	// Gone drops the key from the family: its name reads the built-in value again.
	Gone bool
}

// Result is what a command answers: what to show, what it commits, and what
// it asks of I/O modules.
type Result struct {
	// Text is what to show; where the command's reply is data and the call
	// said --json, Run puts Data there as JSON.
	Text string
	// Data is the reply as data, for a command whose reply is data.
	Data   any
	Writes []Write
	// Requests are what the run asks of I/O modules, each through one of
	// its module's request ports, delivered in order. A failed request stops
	// the list, and the command fails with its reason.
	Requests []Request
	// Then, where set, reads the answers to Requests, one per request in
	// their order, and answers the next step: its own text, writes and next
	// list of requests. The last step's text and data are the reply; every
	// step's writes are committed once all of them have run.
	Then func(answers []any) (Result, error)
}

// Request is one request a run answers: the value it hands its module's
// request port Port, which the wiring binds to an I/O module's verb.
type Request struct {
	Port  string
	Value any
}

// Exchange is one request port or verb as the catalog and the fake index see
// it: what it takes, what it answers, and its one help line.
type Exchange struct {
	// Name is the request port's local name, or the verb's.
	Name string
	// Request is the Go type of what it takes; Answer of what it answers.
	Request, Answer reflect.Type
	Help            string
}

// Deliver hands a request to whatever answers the request port it names: the
// index the verb the wiring binds it to, the fake index the test's answer.
type Deliver func(port string, request any) (any, error)

// CommandDecl is a command as a module declares it, and as every adapter renders it.
type CommandDecl struct {
	// Name is the words that call it: "issue land".
	Name string
	// Usage is the command line after se, the name first, with its flags.
	Usage string
	// Summary is one short line, no flags.
	Summary string
	// Help is what its help says beyond the usage.
	Help string
	// Group is the heading it stands under in the help listing.
	Group string
	// Session offers it in a Claude session as /se <name>.
	Session bool
	// Button offers it as a /se ui button; only a session command is one.
	Button bool
	// Installed has the installed se answer it even when the session works
	// in an SE checkout, whose own se answers every other /se word.
	Installed bool
	// Class is Interactive or Batch: whether a person waits on its answer.
	Class Class
	// Flags are the flags it takes, each with its type, default and help.
	Flags []Flag
	// Words are what it takes beside its flags: none, an issue number, or any words.
	Words Words
	// JSON is set where its reply is data as well as text: it takes --json,
	// and answers its data as JSON there.
	JSON bool
}

// Class says who waits on a command (principle 9). The battery runs every
// interactive command against the fake GitHub and holds it to its budgets.
type Class string

const (
	// Interactive is a command a person types or presses and waits on: it
	// answers from what the snapshot holds, within its time and request budget.
	Interactive Class = "interactive"
	// Batch is a command that must write, or that the fleet, a hook or the
	// battery runs: it goes out at once.
	Batch Class = "batch"
)

// Reader answers the value of a local input port.
type Reader func(port string) any

// Module is one module's declaration: its ports, config and commands, by
// local name only. Declare makes one; its methods are the module contract the
// core and the fake index both speak.
type Module struct {
	name, help string
	io         bool
	inputs     map[string]reflect.Type
	outputs    map[string]*Port
	config     map[string]*Port
	derive     map[string]*derivation
	commands   map[string]*command
	asks       map[string]*Exchange
	verbs      map[string]*verb
	errs       []string
}

type verb struct {
	Exchange
	serve func(any) (any, error)
}

type derivation struct {
	in  inputStruct
	run func(reflect.Value) (any, error)
}

type command struct {
	decl CommandDecl
	in   inputStruct
	run  func(reflect.Value, Args) (Result, error)
}

// inputStruct is a run's input struct: its type, and the local port each field reads.
type inputStruct struct {
	typ   reflect.Type
	ports []string
}

// Declare makes a module from its parts. A broken declaration is kept and
// refused when the index starts or a fake takes the module.
func Declare(name, help string, parts ...Part) *Module {
	m := &Module{
		name: name, help: help,
		inputs:   map[string]reflect.Type{},
		outputs:  map[string]*Port{},
		config:   map[string]*Port{},
		derive:   map[string]*derivation{},
		commands: map[string]*command{},
		asks:     map[string]*Exchange{},
		verbs:    map[string]*verb{},
	}
	if !pathName(name) {
		m.fail("a module needs a name of letters, digits and dashes, or <cluster>/<module>, not %q", name)
	}
	if strings.TrimSpace(help) == "" {
		m.fail("module %s has no help", name)
	}
	for _, p := range parts {
		p.declare(m)
	}
	if len(m.verbs) > 0 && !m.io {
		m.fail("module %s answers verbs, but carries no I/O flag: only an I/O module answers requests", name)
	}
	for port := range m.asks {
		if _, out := m.outputs[port]; out {
			m.fail("request port %s is also an output", port)
		}
		if _, in := m.inputs[port]; in {
			m.fail("request port %s is also an input", port)
		}
	}
	for port, t := range m.inputs {
		if key, ok := strings.CutPrefix(port, ConfigPrefix); ok {
			c, declared := m.config[key]
			switch {
			case !declared:
				m.fail("input %s reads config key %s, which is not declared", port, key)
			case c.Type != t:
				m.fail("input %s is %s, but config key %s is %s", port, t, key, c.Type)
			}
		}
	}
	return m
}

func (m *Module) fail(format string, a ...any) {
	m.errs = append(m.errs, fmt.Sprintf(format, a...))
}

// Name is the module's name, which the wiring file's instances name.
func (m *Module) Name() string { return m.name }

// IO says whether the module carries the I/O flag: it touches its one outside thing.
func (m *Module) IO() bool { return m.io }

// Help is the module's one help line.
func (m *Module) Help() string { return m.help }

// Err is what is wrong with the declaration, or nil.
func (m *Module) Err() error {
	if len(m.errs) == 0 {
		return nil
	}
	return errors.New("module " + m.name + ": " + strings.Join(m.errs, "; "))
}

// Inputs are the ports the module reads, config ones among them, by local name.
func (m *Module) Inputs() []Port {
	var out []Port
	for _, p := range sortedKeys(m.inputs) {
		out = append(out, Port{Port: p, Type: m.inputs[p], Builtin: reflect.Zero(m.inputs[p]).Interface()})
	}
	return out
}

// Outputs are the ports the module writes.
func (m *Module) Outputs() []Port { return ports(m.outputs) }

// Config are the module's config keys; Port is the key.
func (m *Module) Config() []Port { return ports(m.config) }

// Commands are the commands the module declares, by name.
func (m *Module) Commands() []CommandDecl {
	var out []CommandDecl
	for _, n := range sortedKeys(m.commands) {
		out = append(out, m.commands[n].decl)
	}
	return out
}

// Asks are the module's request ports, by local name.
func (m *Module) Asks() []Exchange {
	var out []Exchange
	for _, n := range sortedKeys(m.asks) {
		out = append(out, *m.asks[n])
	}
	return out
}

// Verbs are the verbs the module answers, by name.
func (m *Module) Verbs() []Exchange {
	var out []Exchange
	for _, n := range sortedKeys(m.verbs) {
		out = append(out, m.verbs[n].Exchange)
	}
	return out
}

// Serve answers request with the verb of that name, refusing a request or an
// answer of another type than the verb declares.
func (m *Module) Serve(name string, request any) (any, error) {
	v, ok := m.verbs[name]
	switch {
	case !ok:
		return nil, fmt.Errorf("module %s answers no verb %q", m.name, name)
	case !Fits(request, v.Request):
		return nil, fmt.Errorf("module %s: verb %s takes %s, not %T", m.name, name, v.Request, request)
	}
	return v.serve(request)
}

// Derivations are the outputs a derivation writes.
func (m *Module) Derivations() []string { return sortedKeys(m.derive) }

// ReadsOf answers the local input ports the derivation of output, or the command, reads.
func (m *Module) ReadsOf(name string) []string {
	if d, ok := m.derive[name]; ok {
		return d.in.ports
	}
	if c, ok := m.commands[name]; ok {
		return c.in.ports
	}
	return nil
}

// Derive runs the derivation of output port on what read answers.
func (m *Module) Derive(port string, read Reader) (any, error) {
	d, ok := m.derive[port]
	if !ok {
		return nil, fmt.Errorf("module %s derives no output %q", m.name, port)
	}
	in, err := d.in.fill(read)
	if err != nil {
		return nil, err
	}
	return d.run(in)
}

// Run runs the command name with the words of its call on what read
// answers: it parses them as the command declares, hands each request the run
// answers to deliver in order, and each continuation the answers, and answers
// the last step's text, or its data as JSON where the call said --json, with
// every step's writes. It refuses a request to a port the module does not
// declare, a value or an answer of another type than the port's, and a result
// that writes a port the module's commands do not write.
func (m *Module) Run(name string, read Reader, words []string, deliver Deliver) (Result, error) {
	c, ok := m.commands[name]
	if !ok {
		return Result{}, fmt.Errorf("module %s has no command %q", m.name, name)
	}
	args, err := c.decl.Parse(words)
	if err != nil {
		return Result{}, err
	}
	in, err := c.in.fill(read)
	if err != nil {
		return Result{}, err
	}
	r, err := c.run(in, args)
	var writes []Write
	for err == nil {
		writes = append(writes, r.Writes...)
		var answers []any
		if answers, err = m.deliver(r.Requests, deliver); err != nil || r.Then == nil {
			break
		}
		r, err = r.Then(answers)
	}
	if err != nil {
		return Result{}, err
	}
	r.Writes, r.Requests, r.Then = writes, nil, nil
	if r.Text, err = args.Render(r.Text, r.Data); err != nil {
		return Result{}, err
	}
	return r, m.CheckWrites(r.Writes)
}

// deliver hands each request to deliver in order, and answers the answers;
// the first that fails stops the list, with its reason.
func (m *Module) deliver(requests []Request, deliver Deliver) ([]any, error) {
	answers := make([]any, len(requests))
	for i, q := range requests {
		a, ok := m.asks[q.Port]
		switch {
		case !ok:
			return nil, fmt.Errorf("module %s has no request port %q", m.name, q.Port)
		case !Fits(q.Value, a.Request):
			return nil, fmt.Errorf("module %s: request port %s takes %s, not %T", m.name, q.Port, a.Request, q.Value)
		}
		if deliver == nil {
			return nil, fmt.Errorf("module %s: nothing answers request port %s", m.name, q.Port)
		}
		answer, err := deliver(q.Port, q.Value)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", q.Port, err)
		}
		if !Fits(answer, a.Answer) {
			return nil, fmt.Errorf("module %s: request port %s answers %s, not %T", m.name, q.Port, a.Answer, answer)
		}
		answers[i] = answer
	}
	return answers, nil
}

// CheckWrites refuses a write to anything but one of the module's outputs a
// command writes, or of another type than the port's.
func (m *Module) CheckWrites(writes []Write) error {
	for _, w := range writes {
		o, ok := m.outputs[w.Port]
		switch {
		case !ok:
			return fmt.Errorf("module %s writes no output %q", m.name, w.Port)
		case o.Derived:
			return fmt.Errorf("module %s: output %s is written by its derivation alone", m.name, w.Port)
		case w.Gone && !o.Family:
			return fmt.Errorf("module %s: output %s is no family, and drops no key", m.name, w.Port)
		case !w.Gone && !Fits(w.Value, o.Type):
			return fmt.Errorf("module %s: output %s takes %s, not %T", m.name, w.Port, o.Type, w.Value)
		case o.Family && !Key(w.Key):
			return fmt.Errorf("module %s: output %s is a family, and %q is no key: letters, digits, dots, dashes and underscores", m.name, w.Port, w.Key)
		case !o.Family && w.Key != "":
			return fmt.Errorf("module %s: output %s is no family, and takes no key", m.name, w.Port)
		}
	}
	return nil
}

// OutPort is an output a command writes; Set makes the write.
type OutPort[T any] struct{ port Port }

// Output declares an output port that the module's commands write, with its
// built-in value and its help line.
func Output[T any](port string, builtin T, help string) *OutPort[T] {
	return &OutPort[T]{Port{Port: port, Type: reflect.TypeFor[T](), Builtin: builtin, Help: help}}
}

// Set is a write of v to the port.
func (o *OutPort[T]) Set(v T) Write { return Write{Port: o.port.Port, Value: v} }

func (o *OutPort[T]) declare(m *Module) { m.addOutput(o.port) }

func (m *Module) addOutput(p Port) {
	if !portName(p.Port) {
		m.fail("output %q needs a local name of letters, digits and dashes", p.Port)
	}
	if _, taken := m.outputs[p.Port]; taken {
		m.fail("output %s is declared twice", p.Port)
	}
	if strings.TrimSpace(p.Help) == "" {
		m.fail("output %s has no help", p.Port)
	}
	m.outputs[p.Port] = &p
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

func (o *FamilyPort[T]) declare(m *Module) { m.addOutput(o.port) }

type derivedPart struct {
	port Port
	d    *derivation
	err  error
}

func (p derivedPart) declare(m *Module) {
	m.addOutput(p.port)
	if p.err != nil {
		m.fail("derivation %s: %v", p.port.Port, p.err)
		return
	}
	m.addInputs(p.d.in)
	m.derive[p.port.Port] = p.d
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

// AskPort is a request port: a run asks through it, and the wiring binds it
// to an I/O module's verb that takes Req and answers Ans. Of makes a request,
// Answer reads its answer.
type AskPort[Req, Ans any] struct{ x Exchange }

// Ask declares a request port that takes Req and answers Ans, with its help line.
func Ask[Req, Ans any](port, help string) *AskPort[Req, Ans] {
	return &AskPort[Req, Ans]{Exchange{Name: port, Request: reflect.TypeFor[Req](), Answer: reflect.TypeFor[Ans](), Help: help}}
}

// Of is a request of v through the port.
func (p *AskPort[Req, Ans]) Of(v Req) Request { return Request{Port: p.x.Name, Value: v} }

// Answer reads an answer the port's request got; the delivery checked its type.
func (p *AskPort[Req, Ans]) Answer(a any) Ans {
	v, _ := a.(Ans)
	return v
}

func (p *AskPort[Req, Ans]) declare(m *Module) {
	if !m.exchange(p.x, "request port") {
		return
	}
	if _, taken := m.asks[p.x.Name]; taken {
		m.fail("request port %s is declared twice", p.x.Name)
	}
	x := p.x
	m.asks[x.Name] = &x
}

type verbPart struct{ v *verb }

// Verb declares a verb an I/O module answers: fn does what a request of Req
// asks of the module's outside thing, and answers Ans. A compute module's
// request port that takes Req and answers Ans is wired to it.
func Verb[Req, Ans any](name, help string, fn func(Req) (Ans, error)) Part {
	return verbPart{&verb{
		Exchange: Exchange{Name: name, Request: reflect.TypeFor[Req](), Answer: reflect.TypeFor[Ans](), Help: help},
		serve: func(v any) (any, error) {
			r, _ := v.(Req)
			return fn(r)
		},
	}}
}

func (p verbPart) declare(m *Module) {
	if !m.exchange(p.v.Exchange, "verb") {
		return
	}
	if _, taken := m.verbs[p.v.Name]; taken {
		m.fail("verb %s is declared twice", p.v.Name)
	}
	m.verbs[p.v.Name] = p.v
}

// exchange checks a request port's or verb's name and help.
func (m *Module) exchange(x Exchange, what string) bool {
	if !portName(x.Name) {
		m.fail("%s %q needs a local name of letters, digits and dashes", what, x.Name)
		return false
	}
	if strings.TrimSpace(x.Help) == "" {
		m.fail("%s %s has no help", what, x.Name)
	}
	return true
}

type ioPart struct{}

func (ioPart) declare(m *Module) { m.io = true }

// IO is the I/O flag: the module touches its one outside thing. A module
// without it is a compute module.
func IO() Part { return ioPart{} }

type configPart struct{ port Port }

// Config declares a config key with its built-in value and help line. A run
// reads it as the input port config/<key>.
func Config[T any](key string, builtin T, help string) Part {
	return configPart{Port{Port: key, Type: reflect.TypeFor[T](), Builtin: builtin, Help: help}}
}

func (p configPart) declare(m *Module) {
	if !portName(p.port.Port) {
		m.fail("config key %q needs a local name of letters, digits and dashes", p.port.Port)
	}
	if _, taken := m.config[p.port.Port]; taken {
		m.fail("config key %s is declared twice", p.port.Port)
	}
	if strings.TrimSpace(p.port.Help) == "" {
		m.fail("config key %s has no help", p.port.Port)
	}
	m.config[p.port.Port] = &p.port
}

type commandPart struct {
	c   *command
	err error
}

// Command declares a command: fn reads the input struct In and the call's
// Args, parsed as decl declares them, and answers what to show, its data
// where its reply is data, and what to commit.
func Command[In any](decl CommandDecl, fn func(in In, args Args) (Result, error)) Part {
	in, err := inputsOf(reflect.TypeFor[In]())
	return commandPart{c: &command{decl: decl, in: in, run: func(v reflect.Value, args Args) (Result, error) {
		return fn(v.Interface().(In), args)
	}}, err: err}
}

func (p commandPart) declare(m *Module) {
	d := p.c.decl
	if p.err != nil {
		m.fail("command %q: %v", d.Name, p.err)
		return
	}
	for field, v := range map[string]string{"name": d.Name, "usage": d.Usage, "summary": d.Summary, "help": d.Help, "group": d.Group} {
		if strings.TrimSpace(v) == "" {
			m.fail("command %q has no %s", d.Name, field)
		}
	}
	if d.Button && !d.Session {
		m.fail("command %q is a button but not offered in a session", d.Name)
	}
	if d.Class != Interactive && d.Class != Batch {
		m.fail("command %q has no class: %s or %s", d.Name, Interactive, Batch)
	}
	for _, e := range d.checkFlags() {
		m.fail("%s", e)
	}
	if _, taken := m.commands[d.Name]; taken {
		m.fail("command %q is declared twice", d.Name)
	}
	m.addInputs(p.c.in)
	m.commands[d.Name] = p.c
}

func (m *Module) addInputs(in inputStruct) {
	for i, port := range in.ports {
		t := in.typ.Field(i).Type
		if have, ok := m.inputs[port]; ok && have != t {
			m.fail("input %s is read as %s and as %s", port, have, t)
		}
		m.inputs[port] = t
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

// pathName says whether s is a module's or an instance's name: segments of
// letters, digits and dashes, split by /, such as tally or issues/pull. A
// nested name is a module in a cluster, and its instance owns the names under it.
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
