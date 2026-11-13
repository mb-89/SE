package index

import (
	"errors"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"sync"
)

// Value is what a name reads: its value, and whether anything provided it.
// A name nothing provided, or whose writer is switched off, reads as its
// writer's built-in value.
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
	writer  string // instance.port, or "config of <instance>"
	inst    string // the instance that writes it
	line    int
	typ     reflect.Type
	shape   string
	builtin any
	family  bool
}

// instance is one component instance and where its ports are bound.
type instance struct {
	name    string
	comp    *Component
	line    int
	enabled bool
	offLine int
	in      map[string]string // input port to the name it reads; "" reads the built-in value
	out     map[string]string // output port to the name it writes
	req     map[string]target // request port to the verb it is bound to
	height  int
}

// target is a verb of an I/O instance a request port is bound to.
type target struct {
	inst, verb string
	line       int
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
	// onRun tells a declared instance's process to run its derivations; runs
	// are the instances a commit's wave left to their processes.
	onRun func(instance string, revision uint64)
	runs  map[string]bool
}

var (
	registryMu sync.Mutex
	registry   []*Component
)

// Register adds a component to the ones a binary carries; a component's
// package calls it from init. The start refuses two components of one name.
func Register(c *Component) {
	registryMu.Lock()
	defer registryMu.Unlock()
	registry = append(registry, c)
}

// Registered answers the components registered so far.
func Registered() []*Component {
	registryMu.Lock()
	defer registryMu.Unlock()
	return append([]*Component{}, registry...)
}

// Start checks the catalog the wiring makes of the components and starts it:
// it refuses, naming the port and the wiring line, a name with two writers, an
// input bound to nothing, two types on one wire, a cycle, a broken
// declaration, or a wire to an instance that is switched off. Then every
// derivation of a switched-on instance runs once, and each switched-on
// instance whose component declares an inlet is handed its commit.
func Start(w Wiring, components ...*Component) (*Index, error) {
	ix, err := check(w, components)
	if err != nil {
		return nil, err
	}
	changed := map[string]bool{}
	if err := ix.settle(changed, true); err != nil {
		return nil, err
	}
	if err := ix.inlets(); err != nil {
		return nil, err
	}
	return ix, nil
}

// Collect checks the catalog the wiring makes of the components, as Start
// does, and answers it without starting anything: no derivation runs. A
// surface that renders what the components declared, such as the help, reads it here.
func Collect(w Wiring, components ...*Component) (Catalog, error) {
	ix, err := check(w, components)
	if err != nil {
		return Catalog{}, err
	}
	return ix.catalog, nil
}

// check builds an unstarted index from the wiring and the components, or refuses a broken catalog.
func check(w Wiring, components []*Component) (*Index, error) {
	b := &builder{w: w, comps: map[string]*Component{}, ix: &Index{
		names: map[string]*nameInfo{}, insts: map[string]*instance{}, subs: map[string]map[int]func(Value){},
	}}
	b.build(components)
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

// Catalog is what the components declared, as the wiring binds it.
func (ix *Index) Catalog() Catalog { return ix.catalog }

// Commit writes values to an instance's outputs, as an I/O component commits
// what comes in, and pushes the change. It refuses a port the instance does
// not write, and an instance that is switched off.
func (ix *Index) Commit(instance string, writes ...Write) error {
	in, ok := ix.insts[instance]
	switch {
	case !ok:
		return fmt.Errorf("index: no instance %s", instance)
	case !in.enabled:
		return fmt.Errorf("index: instance %s is switched off (wiring line %d)", instance, in.offLine)
	}
	if err := in.comp.checkWrites(writes, in.comp.Declared()); err != nil {
		return fmt.Errorf("index: instance %s: %w", instance, err)
	}
	return ix.apply(in, writes)
}

// Call runs a command on a snapshot of its instance's inputs: it commits what
// the command writes and pushes the change, delivers its requests in order to
// the verbs the wiring binds them to, and hands the answers to its
// continuation, until a step answers no continuation. A failed request stops
// the command with its reason; what it already committed and requested stands.
// The result holds every step's text, writes and delivered requests.
func (ix *Index) Call(command string, args ...string) (Result, error) {
	c, ok := ix.catalog.Command(command)
	if !ok {
		return Result{}, fmt.Errorf("index: no command %q", command)
	}
	in := ix.insts[c.Instance]
	r, err := in.comp.Run(command, in.reader(ix.Snapshot(), ""), args)
	var done Result
	for {
		if err != nil {
			return done, err
		}
		if r.Text != "" {
			done.Text = strings.TrimPrefix(done.Text+"\n"+r.Text, "\n")
		}
		done.Lines = append(done.Lines, r.Lines...)
		done.Writes = append(done.Writes, r.Writes...)
		if err := ix.apply(in, r.Writes); err != nil {
			return done, err
		}
		answers := make([]any, 0, len(r.Requests))
		for i, a := range r.Requests {
			t := in.req[a.Port]
			ans, err := ix.insts[t.inst].comp.Serve(t.verb, a.Value)
			if err != nil {
				return done, fmt.Errorf("index: %s: request %d of %d, %s.%s to %s.%s, failed: %w", command, i+1, len(r.Requests), in.name, a.Port, t.inst, t.verb, err)
			}
			done.Requests = append(done.Requests, a)
			answers = append(answers, ans)
		}
		if r.Then == nil {
			return done, nil
		}
		r, err = r.Then(answers)
	}
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
	if len(writes) == 0 {
		return nil
	}
	ix.mu.Lock()
	changed := map[string]bool{}
	ix.runs = map[string]bool{}
	ix.commit(in, writes, changed)
	err := ix.settle(changed, false)
	runs, onRun, rev := sortedRuns(ix.runs), ix.onRun, ix.snap.rev
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
	if onRun != nil {
		for _, inst := range runs {
			onRun(inst, rev)
		}
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
		if w.Gone {
			if _, ok := vals[name]; ok {
				changed[name] = true
				delete(vals, name)
			}
			continue
		}
		if old, ok := vals[name]; !ok || !reflect.DeepEqual(old, w.Value) {
			changed[name] = true
		}
		vals[name] = w.Value
	}
	ix.snap = Snapshot{rev: ix.snap.rev + 1, vals: vals, names: ix.names, fams: ix.fams}
}

// settle runs a wave: lowest height first, each derivation of a switched-on
// instance that reads a changed name, or all of them; so each runs once per
// change, after everything it reads has settled. A derivation that reads a
// family runs once per key that changed in it, reading the family at that key.
func (ix *Index) settle(changed map[string]bool, all bool) error {
	var errs []error
	for _, in := range ix.order {
		if !in.enabled {
			continue
		}
		for _, port := range in.comp.Derivations() {
			if in.comp.Declared() {
				// Its own process runs it, told after the commit, and commits what it answers.
				if !all && len(in.runs(port, changed, all, ix.snap)) > 0 && ix.runs != nil {
					ix.runs[in.name] = true
				}
				continue
			}
			for _, key := range in.runs(port, changed, all, ix.snap) {
				v, err := in.comp.Derive(port, in.reader(ix.snap, key))
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
	for _, p := range in.comp.ReadsOf(port) {
		name := in.in[p]
		n := s.names[name]
		switch {
		case n != nil && n.family && in.whole(p, n):
			// A whole family runs it once for any change at any of its keys.
			for c := range changed {
				if _, ok := keyIn(name, c); ok {
					plain = true
				}
			}
		case n != nil && n.family:
			fams[name] = true
		case changed[name]:
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
			if in.whole(port, n) {
				return s.family(name, in.comp.inputs[port])
			}
			if key == "" {
				return n.builtin
			}
			name = atKey(name, key)
		}
		v, _ := s.Read(name)
		return v.V
	}
}

// whole says whether the instance reads the family n at its input port whole.
func (in *instance) whole(port string, n *nameInfo) bool {
	return wholeFamily(in.comp.inputs[port], n)
}

// family answers every key standing in family f as a map of type t,
// map[string]T: empty, never nil, where none stands.
func (s Snapshot) family(f string, t reflect.Type) any {
	m := reflect.MakeMap(t)
	for name, v := range s.vals {
		key, ok := keyIn(f, name)
		if !ok || v == nil {
			continue
		}
		if rv := reflect.ValueOf(v); rv.Type().AssignableTo(t.Elem()) {
			m.SetMapIndex(reflect.ValueOf(key), rv)
		}
	}
	return m.Interface()
}
