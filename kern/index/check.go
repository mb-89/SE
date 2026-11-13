package index

import (
	"fmt"
	"reflect"
	"slices"
	"sort"
	"strings"
)

// builder checks a wiring against the components and builds the index from it.
type builder struct {
	w       Wiring
	comps   map[string]*Component
	ix      *Index
	lenient map[string]bool // inputs, instance.port, whose wire may go without its writer
	errs    []string
}

func (b *builder) fail(line int, format string, a ...any) {
	where := ""
	if line > 0 {
		where = fmt.Sprintf("wiring line %d: ", line)
	}
	b.errs = append(b.errs, where+fmt.Sprintf(format, a...))
}

func (b *builder) build(components []*Component) {
	b.lenient = map[string]bool{}
	for _, c := range components {
		if b.comps[c.Name()] != nil {
			b.fail(0, "two components are named %s", c.Name())
		}
		b.comps[c.Name()] = c
		if err := c.Err(); err != nil {
			b.fail(0, "%v", err)
		}
	}
	b.instances()
	refs := b.wires()
	b.outputs()
	b.config()
	b.inputs(refs)
	b.requests()
	b.heights()
	b.ix.snap = Snapshot{vals: b.ix.snap.vals, names: b.ix.names, fams: b.ix.fams}
	b.ix.catalog = b.catalog()
}

func (b *builder) instances() {
	for _, wi := range b.w.Instances {
		c := b.comps[wi.Component]
		switch {
		case !pathName(wi.Name):
			b.fail(wi.Line, "instance %q needs a name of letters, digits and dashes, or a nested one such as issues/pull", wi.Name)
		case b.ix.insts[wi.Name] != nil:
			b.fail(wi.Line, "instance %s is named twice", wi.Name)
		case c == nil:
			b.fail(wi.Line, "instance %s: no component %s is registered", wi.Name, wi.Component)
		default:
			in := &instance{
				name: wi.Name, comp: c, line: wi.Line, enabled: wi.Enabled, offLine: wi.OffLine,
				in: map[string]string{}, out: map[string]string{}, req: map[string]target{},
			}
			for _, o := range c.Outputs() {
				in.out[o.Port] = wi.Name + "/" + o.Port
				if o.Family {
					in.out[o.Port] = wi.Name + "/<key>/" + o.Port
				}
			}
			b.ix.insts[wi.Name] = in
		}
	}
}

// owner answers the instance that owns a name: the one with the longest name
// that is the name itself or a path above it, so issues/pull owns
// issues/pull/open even beside an instance issues. A name under no instance,
// such as numbers/count, has no owner, and "" answers it; any writer may take it.
func (b *builder) owner(name string) string {
	for p := name; p != ""; {
		if b.ix.insts[p] != nil {
			return p
		}
		i := strings.LastIndex(p, "/")
		if i < 0 {
			break
		}
		p = p[:i]
	}
	return ""
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
	requestPort
	verbPort
)

func (b *builder) kind(inst, port string) portKind {
	c := b.ix.insts[inst].comp
	if _, ok := c.outputs[port]; ok {
		return outputPort
	}
	if _, ok := c.inputs[port]; ok && !strings.HasPrefix(port, ConfigPrefix) {
		return inputPort
	}
	if _, ok := c.requests[port]; ok {
		return requestPort
	}
	if _, ok := c.verbs[port]; ok {
		return verbPort
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
		kind := b.kind(inst, port)
		if w.Builtin && kind != inputPort {
			b.fail(w.Line, "%s is no input: only an input may go without its writer", w.Port)
			continue
		}
		switch kind {
		case noPort, verbPort:
			b.fail(w.Line, "instance %s has no port %s", inst, port)
		case outputPort:
			out := b.ix.insts[inst].comp.outputs[port]
			switch {
			case toIsPort && b.kind(toInst, toPort) == inputPort:
				refs = append(refs, ref{in: toInst, port: toPort, outInst: inst, outPort: port, line: w.Line})
				wired[w.To] = w.Line
			case toIsPort:
				b.fail(w.Line, "%s and %s are both outputs: a name with two writers", w.Port, w.To)
			case !globalName(w.To):
				b.fail(w.Line, "%s: %q is no name: segments of letters, digits and dashes, split by /, and at most one key segment such as <id>", w.Port, w.To)
			case out.Family && !familyName(w.To):
				b.fail(w.Line, "%s writes at keys, and %q is no family: give it one key segment, such as <id>", w.Port, w.To)
			case !out.Family && familyName(w.To):
				b.fail(w.Line, "%s writes no keys, and %q is a family", w.Port, w.To)
			default:
				b.ix.insts[inst].out[port] = w.To
			}
		case inputPort:
			b.lenient[w.Port] = w.Builtin
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
		case requestPort:
			if !toIsPort || b.kind(toInst, toPort) != verbPort {
				b.fail(w.Line, "request port %s is bound to %s, which is no verb of an I/O instance", w.Port, w.To)
				continue
			}
			b.ix.insts[inst].req[port] = target{inst: toInst, verb: toPort, line: w.Line}
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
		for _, o := range in.comp.Outputs() {
			name, writer := in.out[o.Port], inst+"."+o.Port
			line := lines[writer]
			if line == 0 {
				line = in.line
			}
			if owner := b.owner(name); owner != "" && owner != inst {
				b.fail(line, "name %s lies under instance %s, which owns the names %s/...: %s may not write it", name, owner, owner, writer)
				continue
			}
			if n, taken := b.ix.names[name]; taken {
				b.fail(line, "name %s has two writers: %s (line %d) and %s", name, n.writer, n.line, writer)
				continue
			}
			b.ix.names[name] = &nameInfo{writer: writer, inst: inst, line: line, typ: o.Type, shape: o.Shape, builtin: o.Builtin, family: o.Family}
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
		if in == nil || in.line != wi.Line {
			continue
		}
		declared := map[string]bool{}
		for _, c := range in.comp.Config() {
			declared[c.Port] = true
			name := wi.Name + "/" + ConfigPrefix + c.Port
			if owner := b.owner(name); owner != "" && owner != wi.Name {
				b.fail(wi.Line, "name %s lies under instance %s, which owns the names %s/...: the config of %s may not write it", name, owner, owner, wi.Name)
				continue
			}
			if n, taken := b.ix.names[name]; taken {
				b.fail(wi.Line, "name %s has two writers: %s (line %d) and the wiring's config", name, n.writer, n.line)
				continue
			}
			b.ix.names[name] = &nameInfo{writer: "config of " + wi.Name, line: wi.Line, typ: c.Type, shape: c.Shape, builtin: c.Builtin}
			in.in[ConfigPrefix+c.Port] = name
			if given, ok := wi.Config[c.Port]; ok {
				v, err := configValue(given.Value, c.Type)
				if err != nil {
					b.fail(given.Line, "instance %s: config %s takes %s: %v", wi.Name, c.Port, c.Type, err)
					continue
				}
				vals[name] = v
			}
		}
		for _, key := range sortedKeys(wi.Config) {
			if !declared[key] {
				b.fail(wi.Config[key].Line, "instance %s: component %s has no config key %s", wi.Name, wi.Component, key)
			}
		}
	}
	b.ix.snap.vals = vals
}

// inputs checks every input is bound to a name a writer writes, in its type,
// and that a switched-on instance reads no name of a switched-off one unless
// its wire may go without it.
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
		for _, p := range in.comp.Inputs() {
			port := inst + "." + p.Port
			name, bound := in.in[p.Port]
			n := b.ix.names[name]
			switch {
			case !bound:
				b.fail(in.line, "input %s is bound to nothing: wire it, or mark it %s", port, BuiltIn)
			case name == "":
			case n == nil:
				b.fail(lines[port], "input %s is bound to %s, which nothing writes", port, name)
			case n.family && wholeFamily(p.Type, n) && n.shape == p.Shape:
				// It reads the whole family, every key standing, as one map.
			case n.family && commandReads(in.comp, p.Port):
				b.fail(lines[port], "input %s is bound to the family %s, and a command reads it: only a derivation reads a family at the key that changed, and a command reads it whole as map[string]%s", port, name, typeName(n.typ, n.shape))
			case n.typ != p.Type || n.shape != p.Shape:
				b.fail(lines[port], "two types on one wire: %s reads %s as %s, but %s writes %s", port, name, typeName(p.Type, p.Shape), n.writer, typeName(n.typ, n.shape))
			case in.enabled && n.inst != "" && !b.ix.insts[n.inst].enabled && !b.lenient[port]:
				w := b.ix.insts[n.inst]
				b.fail(lines[port], "input %s is bound to %s, and its writer %s is switched off on line %d: switch it on, or let the wire go without it with builtin = true", port, name, w.name, w.offLine)
			}
		}
	}
}

// requests checks every request port is bound to a verb that takes its
// request and gives its answer, of a switched-on instance where the asking one is on.
func (b *builder) requests() {
	for _, inst := range sortedKeys(b.ix.insts) {
		in := b.ix.insts[inst]
		for _, r := range in.comp.Requests() {
			port := inst + "." + r.Port
			t, bound := in.req[r.Port]
			if !bound {
				b.fail(in.line, "request port %s is bound to nothing: wire it to a verb of an I/O instance", port)
				continue
			}
			to := b.ix.insts[t.inst]
			v := to.comp.verbs[t.verb].decl
			switch {
			case v.Req != r.Req || v.Ans != r.Ans || v.ReqShape != r.ReqShape || v.AnsShape != r.AnsShape:
				b.fail(t.line, "two types on one wire: %s sends %s and reads %s, but %s.%s takes %s and answers %s", port,
					typeName(r.Req, r.ReqShape), typeName(r.Ans, r.AnsShape), t.inst, t.verb, typeName(v.Req, v.ReqShape), typeName(v.Ans, v.AnsShape))
			case in.enabled && !to.enabled:
				b.fail(t.line, "request port %s is bound to %s.%s, and %s is switched off on line %d", port, t.inst, t.verb, t.inst, to.offLine)
			}
		}
	}
}

// heights orders the instances so each runs after every instance it reads,
// and refuses a cycle.
func (b *builder) heights() {
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
			if n := b.ix.names[name]; n != nil && n.inst != "" {
				h = max(h, visit(n.inst, append(path, inst))+1)
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

// typeName is how a refusal names a type: its shape where it carries one.
func typeName(t reflect.Type, shape string) string {
	if shape != "" {
		return shape
	}
	return t.String()
}

// commandReads says whether a command of c reads the local input port.
// wholeFamily says whether an input of type t reads the family n whole: t is
// map[string]T, T the family's type, and the map holds every key standing.
func wholeFamily(t reflect.Type, n *nameInfo) bool {
	return n != nil && n.family && t != nil && t.Kind() == reflect.Map &&
		t.Key().Kind() == reflect.String && t.Elem() == n.typ
}

func commandReads(c *Component, port string) bool {
	for _, k := range c.Commands() {
		if slices.Contains(c.ReadsOf(k.Name), port) {
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
