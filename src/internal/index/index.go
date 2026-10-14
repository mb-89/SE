package index

import (
	"errors"
	"fmt"
	"reflect"
	"slices"
	"sort"
	"strings"
	"sync"
)

// Value is what a name reads: its value, and whether anything provided it.
// A name nothing provided reads as its writer's built-in value.
type Value struct {
	V        any
	Provided bool
}

// Snapshot is the store at one revision. It never changes: a commit makes a new one.
type Snapshot struct {
	rev   uint64
	vals  map[string]any
	names map[string]*nameInfo
	fams  []string // the families among names, sorted
}

// Revision is the store's revision this snapshot holds; every commit raises it.
func (s Snapshot) Revision() uint64 { return s.rev }

// Read answers the value of a name at this snapshot's revision. A name in a
// family, such as session/s1/events in session/<id>/events, reads the value
// standing at its key, or the family's built-in value.
func (s Snapshot) Read(name string) (Value, error) {
	family, _, err := s.lookup(name)
	if err != nil {
		return Value{}, err
	}
	if v, ok := s.vals[name]; ok {
		return Value{V: v, Provided: true}, nil
	}
	return Value{V: s.names[family].builtin}, nil
}

// lookup answers the declared name a name reads: itself, or the family it
// lies in and its key there. A family itself is no name to read.
func (s Snapshot) lookup(name string) (declared, key string, err error) {
	if n, ok := s.names[name]; ok {
		if n.family {
			return "", "", fmt.Errorf("%s is a family: read a name in it, at a key", name)
		}
		return name, "", nil
	}
	for _, f := range s.fams {
		if key, ok := keyIn(f, name); ok {
			return f, key, nil
		}
	}
	return "", "", fmt.Errorf("no name %s", name)
}

// nameInfo is what the index knows of a name: its one writer, type and
// built-in value, and whether it is a family.
type nameInfo struct {
	writer  string
	line    int
	typ     reflect.Type
	builtin any
	family  bool
}

// instance is one module instance and where its ports are bound.
type instance struct {
	name   string
	mod    *Module
	line   int
	in     map[string]string // input port to the name it reads; "" reads the built-in value
	out    map[string]string // output port to the name it writes
	height int
}

// Index is a started index: the store, its names and writers, the running
// instances and the catalog. It is safe to use from many goroutines; it runs
// one commit and the changes it pushes at a time.
type Index struct {
	mu      sync.Mutex
	names   map[string]*nameInfo
	fams    []string
	insts   map[string]*instance
	order   []*instance // by height, then name
	snap    Snapshot
	subs    map[string]map[int]func(Value)
	nextSub int
	catalog Catalog
}

var (
	registryMu sync.Mutex
	registry   []*Module
)

// Register adds a module to the ones a binary carries; a module's package
// calls it from init. The start refuses two modules of one name.
func Register(m *Module) {
	registryMu.Lock()
	defer registryMu.Unlock()
	registry = append(registry, m)
}

// Registered answers the modules registered so far.
func Registered() []*Module {
	registryMu.Lock()
	defer registryMu.Unlock()
	return append([]*Module{}, registry...)
}

// Start checks the catalog the wiring makes of the modules and starts it: it
// refuses, naming the port and the wiring line, a name with two writers, an
// input bound to nothing, two types on one wire, a cycle, or a broken
// declaration. Then every derivation runs once.
func Start(w Wiring, modules ...*Module) (*Index, error) {
	ix, err := check(w, modules)
	if err != nil {
		return nil, err
	}
	changed := map[string]bool{}
	if err := ix.settle(changed, true); err != nil {
		return nil, err
	}
	return ix, nil
}

// Collect checks the catalog the wiring makes of the modules, as Start does,
// and answers it without starting anything: no derivation runs. An adapter
// that renders what the modules declared, such as the help, reads it here.
func Collect(w Wiring, modules ...*Module) (Catalog, error) {
	ix, err := check(w, modules)
	if err != nil {
		return Catalog{}, err
	}
	return ix.catalog, nil
}

// check builds an unstarted index from the wiring and the modules, or refuses a broken catalog.
func check(w Wiring, modules []*Module) (*Index, error) {
	b := &builder{w: w, mods: map[string]*Module{}, ix: &Index{
		names: map[string]*nameInfo{}, insts: map[string]*instance{}, subs: map[string]map[int]func(Value){},
	}}
	b.build(modules)
	if len(b.errs) > 0 {
		return nil, errors.New("index: the catalog is broken:\n  " + strings.Join(b.errs, "\n  "))
	}
	return b.ix, nil
}

// Snapshot is the store as it stands.
func (ix *Index) Snapshot() Snapshot {
	ix.mu.Lock()
	defer ix.mu.Unlock()
	return ix.snap
}

// Read answers a name's value as it stands.
func (ix *Index) Read(name string) (Value, error) { return ix.Snapshot().Read(name) }

// Catalog is what the modules declared, as the wiring binds it.
func (ix *Index) Catalog() Catalog { return ix.catalog }

// Commit writes values to an instance's outputs, as an I/O module commits
// what comes in, and pushes the change. It refuses a port the instance does
// not write.
func (ix *Index) Commit(instance string, writes ...Write) error {
	in, ok := ix.insts[instance]
	if !ok {
		return fmt.Errorf("index: no instance %s", instance)
	}
	if err := in.mod.CheckWrites(writes); err != nil {
		return fmt.Errorf("index: instance %s: %w", instance, err)
	}
	return ix.apply(in, writes)
}

// Call runs a command on a snapshot of its instance's inputs, commits what it
// writes, pushes the change, and answers its result.
func (ix *Index) Call(command string, args ...string) (Result, error) {
	c, ok := ix.catalog.Command(command)
	if !ok {
		return Result{}, fmt.Errorf("index: no command %q", command)
	}
	in := ix.insts[c.Instance]
	r, err := in.mod.Run(command, in.reader(ix.Snapshot(), ""), args)
	if err != nil {
		return Result{}, err
	}
	return r, ix.apply(in, r.Writes)
}

// Subscribe calls fn with a name's value after each commit that changes it,
// until cancel is called.
func (ix *Index) Subscribe(name string, fn func(Value)) (cancel func(), err error) {
	ix.mu.Lock()
	defer ix.mu.Unlock()
	if _, _, err := ix.snap.lookup(name); err != nil {
		return nil, fmt.Errorf("index: %w", err)
	}
	if ix.subs[name] == nil {
		ix.subs[name] = map[int]func(Value){}
	}
	id := ix.nextSub
	ix.nextSub++
	ix.subs[name][id] = fn
	return func() {
		ix.mu.Lock()
		defer ix.mu.Unlock()
		delete(ix.subs[name], id)
	}, nil
}

// apply commits an instance's writes, runs every derivation that reads what
// changed, and then tells the subscribers of each changed name.
func (ix *Index) apply(in *instance, writes []Write) error {
	ix.mu.Lock()
	changed := map[string]bool{}
	ix.commit(in, writes, changed)
	err := ix.settle(changed, false)
	type push struct {
		fn func(Value)
		v  Value
	}
	var pushes []push
	for _, name := range sortedKeys(changed) {
		v, _ := ix.snap.Read(name)
		ids := make([]int, 0, len(ix.subs[name]))
		for id := range ix.subs[name] {
			ids = append(ids, id)
		}
		sort.Ints(ids)
		for _, id := range ids {
			pushes = append(pushes, push{ix.subs[name][id], v})
		}
	}
	ix.mu.Unlock()
	for _, p := range pushes {
		p.fn(p.v)
	}
	return err
}

// commit makes the next snapshot with the writes in it, and marks each name whose value changed.
func (ix *Index) commit(in *instance, writes []Write, changed map[string]bool) {
	vals := make(map[string]any, len(ix.snap.vals)+len(writes))
	for k, v := range ix.snap.vals {
		vals[k] = v
	}
	for _, w := range writes {
		name := in.out[w.Port]
		if w.Key != "" {
			name = atKey(name, w.Key)
		}
		if old, ok := vals[name]; !ok || !reflect.DeepEqual(old, w.Value) {
			changed[name] = true
		}
		vals[name] = w.Value
	}
	ix.snap = Snapshot{rev: ix.snap.rev + 1, vals: vals, names: ix.names, fams: ix.fams}
}

// settle runs, lowest height first, each derivation that reads a changed
// name, or all of them; so each runs once per change, after everything it
// reads has settled. A derivation that reads a family runs once per key that
// changed in it, reading the family at that key.
func (ix *Index) settle(changed map[string]bool, all bool) error {
	var errs []error
	for _, in := range ix.order {
		for _, port := range in.mod.Derivations() {
			for _, key := range in.runs(port, changed, all, ix.snap) {
				v, err := in.mod.Derive(port, in.reader(ix.snap, key))
				if err != nil {
					errs = append(errs, fmt.Errorf("index: %s.%s: %w", in.name, port, err))
					continue
				}
				ix.commit(in, []Write{{Port: port, Value: v}}, changed)
			}
		}
	}
	return errors.Join(errs...)
}

// runs answers the keys the derivation of port runs at for this change: none
// where it reads nothing that changed, and "" where it reads no family or no
// key stands in one. A change of a plain name it reads, or a start, runs it at
// every key that stands in the families it reads.
func (in *instance) runs(port string, changed map[string]bool, all bool, s Snapshot) []string {
	fams := map[string]bool{}
	plain := all
	for _, p := range in.mod.ReadsOf(port) {
		name := in.in[p]
		if n := s.names[name]; n != nil && n.family {
			fams[name] = true
		} else if changed[name] {
			plain = true
		}
	}
	keys := map[string]bool{}
	if len(fams) > 0 {
		at := func(name string) {
			if f, key, err := s.lookup(name); err == nil && fams[f] {
				keys[key] = true
			}
		}
		for name := range changed {
			at(name)
		}
		if plain {
			for name := range s.vals {
				at(name)
			}
		}
	}
	switch {
	case len(keys) > 0:
		return sortedKeys(keys)
	case plain:
		return []string{""}
	}
	return nil
}

// reader answers the instance's inputs from a snapshot, by local port; an
// input bound to a family reads it at key, or its built-in value where key is "".
func (in *instance) reader(s Snapshot, key string) Reader {
	return func(port string) any {
		name := in.in[port]
		if name == "" {
			return nil
		}
		if n := s.names[name]; n != nil && n.family {
			if key == "" {
				return n.builtin
			}
			name = atKey(name, key)
		}
		v, _ := s.Read(name)
		return v.V
	}
}

// builder checks a wiring against the modules and builds the index from it.
type builder struct {
	w    Wiring
	mods map[string]*Module
	ix   *Index
	errs []string
}

func (b *builder) fail(line int, format string, a ...any) {
	where := ""
	if line > 0 {
		where = fmt.Sprintf("wiring line %d: ", line)
	}
	b.errs = append(b.errs, where+fmt.Sprintf(format, a...))
}

func (b *builder) build(modules []*Module) {
	for _, m := range modules {
		if b.mods[m.Name()] != nil {
			b.fail(0, "two modules are named %s", m.Name())
		}
		b.mods[m.Name()] = m
		if err := m.Err(); err != nil {
			b.fail(0, "%v", err)
		}
	}
	b.instances()
	refs := b.wires()
	b.outputs()
	b.config()
	b.inputs(refs)
	b.heights()
	b.ix.snap = Snapshot{vals: b.ix.snap.vals, names: b.ix.names, fams: b.ix.fams}
	b.ix.catalog = b.catalog()
}

func (b *builder) instances() {
	for _, wi := range b.w.Instances {
		m := b.mods[wi.Module]
		switch {
		case !portName(wi.Name):
			b.fail(wi.Line, "instance %q needs a name of letters, digits and dashes", wi.Name)
		case b.ix.insts[wi.Name] != nil:
			b.fail(wi.Line, "instance %s is named twice", wi.Name)
		case m == nil:
			b.fail(wi.Line, "instance %s: no module %s is registered", wi.Name, wi.Module)
		default:
			in := &instance{name: wi.Name, mod: m, line: wi.Line, in: map[string]string{}, out: map[string]string{}}
			for _, o := range m.Outputs() {
				in.out[o.Port] = wi.Name + "/" + o.Port
				if o.Family {
					in.out[o.Port] = wi.Name + "/<key>/" + o.Port
				}
			}
			b.ix.insts[wi.Name] = in
		}
	}
}

// ref is an input bound to another instance's output port.
type ref struct {
	in, port, outInst, outPort string
	line                       int
}

type portKind int

const (
	noPort portKind = iota
	inputPort
	outputPort
)

func (b *builder) kind(inst, port string) portKind {
	m := b.ix.insts[inst].mod
	if _, ok := m.outputs[port]; ok {
		return outputPort
	}
	if _, ok := m.inputs[port]; ok && !strings.HasPrefix(port, ConfigPrefix) {
		return inputPort
	}
	return noPort
}

// wires binds each wired port; it answers the inputs bound port to port, which
// bind once every output has its name.
func (b *builder) wires() []ref {
	var refs []ref
	wired := map[string]int{}
	for _, w := range b.w.Wires {
		inst, port, ok := splitPort(w.Port, b.ix.insts)
		if !ok {
			b.fail(w.Line, "%s is no port of an instance", w.Port)
			continue
		}
		if first, twice := wired[w.Port]; twice {
			b.fail(w.Line, "%s is wired twice, first on line %d", w.Port, first)
			continue
		}
		wired[w.Port] = w.Line
		toInst, toPort, toIsPort := splitPort(w.To, b.ix.insts)
		switch b.kind(inst, port) {
		case noPort:
			b.fail(w.Line, "instance %s has no port %s", inst, port)
		case outputPort:
			switch {
			case toIsPort && b.kind(toInst, toPort) == inputPort:
				refs = append(refs, ref{in: toInst, port: toPort, outInst: inst, outPort: port, line: w.Line})
				wired[w.To] = w.Line
			case toIsPort:
				b.fail(w.Line, "%s and %s are both outputs: a name with two writers", w.Port, w.To)
			case !globalName(w.To):
				b.fail(w.Line, "%s: %q is no name: segments of letters, digits and dashes, split by /, and at most one key segment such as <id>", w.Port, w.To)
			case b.ix.insts[inst].mod.outputs[port].Family && !familyName(w.To):
				b.fail(w.Line, "%s writes at keys, and %q is no family: give it one key segment, such as <id>", w.Port, w.To)
			case !b.ix.insts[inst].mod.outputs[port].Family && familyName(w.To):
				b.fail(w.Line, "%s writes no keys, and %q is a family", w.Port, w.To)
			default:
				b.ix.insts[inst].out[port] = w.To
			}
		case inputPort:
			switch {
			case w.To == BuiltIn:
				b.ix.insts[inst].in[port] = ""
			case toIsPort && b.kind(toInst, toPort) == outputPort:
				refs = append(refs, ref{in: inst, port: port, outInst: toInst, outPort: toPort, line: w.Line})
			case toIsPort:
				b.fail(w.Line, "%s is bound to %s, which is no output: an input bound to nothing", w.Port, w.To)
			case !globalName(w.To):
				b.fail(w.Line, "%s: %q is no name: segments of letters, digits and dashes, split by /, and at most one key segment such as <id>", w.Port, w.To)
			default:
				b.ix.insts[inst].in[port] = w.To
			}
		}
	}
	return refs
}

// outputs gives every output's name its one writer.
func (b *builder) outputs() {
	lines := map[string]int{}
	for _, w := range b.w.Wires {
		lines[w.Port] = w.Line
	}
	for _, inst := range sortedKeys(b.ix.insts) {
		in := b.ix.insts[inst]
		for _, o := range in.mod.Outputs() {
			name, writer := in.out[o.Port], inst+"."+o.Port
			line := lines[writer]
			if line == 0 {
				line = in.line
			}
			if n, taken := b.ix.names[name]; taken {
				b.fail(line, "name %s has two writers: %s (line %d) and %s", name, n.writer, n.line, writer)
				continue
			}
			b.ix.names[name] = &nameInfo{writer: writer, line: line, typ: o.Type, builtin: o.Builtin, family: o.Family}
			if o.Family {
				b.ix.fams = append(b.ix.fams, name)
			}
		}
	}
	b.overlaps()
}

// overlaps refuses two families that hold the same names, and a name that
// lies in a family: either is a name with two writers.
func (b *builder) overlaps() {
	sort.Strings(b.ix.fams)
	for i, f := range b.ix.fams {
		for _, g := range b.ix.fams[i+1:] {
			if atKey(f, "") == atKey(g, "") {
				n, m := b.ix.names[f], b.ix.names[g]
				b.fail(m.line, "families %s and %s hold the same names: two writers, %s (line %d) and %s", f, g, n.writer, n.line, m.writer)
			}
		}
		for _, name := range sortedKeys(b.ix.names) {
			if _, in := keyIn(f, name); in {
				n, m := b.ix.names[f], b.ix.names[name]
				b.fail(m.line, "name %s lies in family %s: two writers, %s (line %d) and %s", name, f, n.writer, n.line, m.writer)
			}
		}
	}
}

// config names each instance's config keys, under <instance>/config/<key>,
// with the value the wiring gives it, and binds the inputs that read them.
func (b *builder) config() {
	vals := map[string]any{}
	for _, wi := range b.w.Instances {
		in := b.ix.insts[wi.Name]
		if in == nil {
			continue
		}
		declared := map[string]bool{}
		for _, c := range in.mod.Config() {
			declared[c.Port] = true
			name := wi.Name + "/" + ConfigPrefix + c.Port
			if n, taken := b.ix.names[name]; taken {
				b.fail(wi.Line, "name %s has two writers: %s (line %d) and the wiring's config", name, n.writer, n.line)
				continue
			}
			b.ix.names[name] = &nameInfo{writer: "config of " + wi.Name, line: wi.Line, typ: c.Type, builtin: c.Builtin}
			in.in[ConfigPrefix+c.Port] = name
			if node, given := wi.Config[c.Port]; given {
				v, err := configValue(node, c.Type)
				if err != nil {
					b.fail(node.Line, "instance %s: config %s takes %s: %v", wi.Name, c.Port, c.Type, err)
					continue
				}
				vals[name] = v
			}
		}
		for _, key := range sortedKeys(wi.Config) {
			if !declared[key] {
				b.fail(wi.Config[key].Line, "instance %s: module %s has no config key %s", wi.Name, wi.Module, key)
			}
		}
	}
	b.ix.snap.vals = vals
}

// inputs checks every input is bound to a name a writer writes, in its type.
func (b *builder) inputs(refs []ref) {
	lines := map[string]int{}
	for _, w := range b.w.Wires {
		lines[w.Port] = w.Line
	}
	for _, r := range refs {
		in := b.ix.insts[r.in]
		in.in[r.port] = b.ix.insts[r.outInst].out[r.outPort]
		lines[r.in+"."+r.port] = r.line
	}
	for _, inst := range sortedKeys(b.ix.insts) {
		in := b.ix.insts[inst]
		for _, p := range in.mod.Inputs() {
			port := inst + "." + p.Port
			name, bound := in.in[p.Port]
			switch {
			case !bound:
				b.fail(in.line, "input %s is bound to nothing: wire it, or mark it %s", port, BuiltIn)
			case name == "":
			case b.ix.names[name] == nil:
				b.fail(lines[port], "input %s is bound to %s, which nothing writes", port, name)
			case b.ix.names[name].family && commandReads(in.mod, p.Port):
				b.fail(lines[port], "input %s is bound to the family %s, and a command reads it: only a derivation reads a family, at the key that changed", port, name)
			case b.ix.names[name].typ != p.Type:
				n := b.ix.names[name]
				b.fail(lines[port], "two types on one wire: %s reads %s as %s, but %s writes %s", port, name, p.Type, n.writer, n.typ)
			}
		}
	}
}

// heights orders the instances so each runs after every instance it reads,
// and refuses a cycle.
func (b *builder) heights() {
	writerOf := map[string]string{}
	for name, n := range b.ix.names {
		if inst, _, ok := strings.Cut(n.writer, "."); ok {
			writerOf[name] = inst
		}
	}
	const (
		unseen = iota
		visiting
		done
	)
	state := map[string]int{}
	var visit func(inst string, path []string) int
	visit = func(inst string, path []string) int {
		in := b.ix.insts[inst]
		switch state[inst] {
		case visiting:
			b.fail(in.line, "a cycle: %s", strings.Join(append(path, inst), " reads "))
			return 0
		case done:
			return in.height
		}
		state[inst] = visiting
		h := 0
		for _, name := range sortedValues(in.in) {
			if w, ok := writerOf[name]; ok {
				h = max(h, visit(w, append(path, inst))+1)
			}
		}
		state[inst] = done
		in.height = h
		return h
	}
	for _, inst := range sortedKeys(b.ix.insts) {
		visit(inst, nil)
		b.ix.order = append(b.ix.order, b.ix.insts[inst])
	}
	sort.SliceStable(b.ix.order, func(i, j int) bool { return b.ix.order[i].height < b.ix.order[j].height })
}

// commandReads says whether a command of m reads the local input port.
func commandReads(m *Module, port string) bool {
	for _, c := range m.Commands() {
		if slices.Contains(m.ReadsOf(c.Name), port) {
			return true
		}
	}
	return false
}

// globalName says whether s is a name: segments of letters, digits and
// dashes, split by /, at most one of them a key segment such as <id>.
func globalName(s string) bool {
	keys := 0
	for _, seg := range strings.Split(s, "/") {
		switch {
		case keySegment(seg):
			keys++
		case !portName(seg):
			return false
		}
	}
	return keys <= 1
}

// familyName says whether s is a family: a name with one key segment.
func familyName(s string) bool {
	if !globalName(s) {
		return false
	}
	return slices.ContainsFunc(strings.Split(s, "/"), keySegment)
}

// keySegment says whether seg is a key segment: <name>.
func keySegment(seg string) bool {
	inner, ok := strings.CutPrefix(seg, "<")
	inner, closed := strings.CutSuffix(inner, ">")
	return ok && closed && portName(inner)
}

// atKey is the name at key in family f.
func atKey(f, key string) string {
	segs := strings.Split(f, "/")
	for i, seg := range segs {
		if keySegment(seg) {
			segs[i] = key
		}
	}
	return strings.Join(segs, "/")
}

// keyIn answers the key name stands at in family f, if it lies in f.
func keyIn(f, name string) (string, bool) {
	fs, ns := strings.Split(f, "/"), strings.Split(name, "/")
	if len(fs) != len(ns) {
		return "", false
	}
	key := ""
	for i, seg := range fs {
		switch {
		case keySegment(seg):
			key = ns[i]
		case seg != ns[i]:
			return "", false
		}
	}
	return key, Key(key)
}

func sortedValues(m map[string]string) []string {
	var out []string
	for _, k := range sortedKeys(m) {
		if m[k] != "" {
			out = append(out, m[k])
		}
	}
	return out
}
