package index

import (
	"errors"
	"fmt"
	"os"
	"reflect"
	"sort"
	"strings"
	"time"

	"github.com/pelletier/go-toml/v2"
	"github.com/pelletier/go-toml/v2/unstable"
)

// WiringFile is the wiring file's name, at the root of the application that
// starts the index. The index reads it at start: a component in another
// language is not compiled in, and the fake core in Python reads the same
// file with tomllib.
const WiringFile = "wiring.toml"

// BuiltIn is what a wire names to leave an input unbound: it reads its type's zero value.
const BuiltIn = "built-in"

// Wiring is the wiring file: the component instances and the wires that bind
// their ports. It is the only place that knows the global layout.
//
//	[instances.counter]
//	component = "counter"
//	config = { step = 2 }
//
//	[instances.report]
//	component = "report"
//
//	[instances."issues/pull"]          # nested: it owns the names issues/pull/...
//	component = "issues/pull"
//	enabled = false                    # switched off: its names read their built-in values
//
//	[wires]
//	"counter.count" = "numbers/count"  # an output to a name
//	"report.total" = "counter.count"   # an input to another instance's port
//	"report.extra" = "built-in"        # an input left unbound
//	"report.open" = { to = "issues/pull/open", builtin = true }  # may go without its writer
//	"report.file" = "ledger.append"    # a request port to an I/O component's verb
type Wiring struct {
	Instances []Instance
	Wires     []Wire
}

// Instance is one component instance: its name, plain or nested as
// <group>/<name>, its component, whether it is switched on, and the config
// values the wiring gives it.
type Instance struct {
	Name, Component string
	// Enabled is false where the wiring switches the instance off; OffLine is that switch's line.
	Enabled bool
	OffLine int
	Config  map[string]ConfigValue
	Line    int
}

// ConfigValue is one config value as the wiring file gives it, and its line.
type ConfigValue struct {
	Value any
	Line  int
}

// Wire binds a port, instance.port, to a name, another instance's port, a
// verb or BuiltIn. Builtin lets an input go without its writer: where the
// writer is switched off, it reads the writer's built-in value.
type Wire struct {
	Port, To string
	Builtin  bool
	Line     int
}

// ReadWiring reads the wiring file at path.
func ReadWiring(path string) (Wiring, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Wiring{}, fmt.Errorf("wiring: %w", err)
	}
	w, err := ParseWiring(data)
	if err != nil {
		return Wiring{}, fmt.Errorf("%s: %w", path, err)
	}
	return w, nil
}

// ParseWiring reads a wiring file's text.
func ParseWiring(data []byte) (Wiring, error) {
	var doc map[string]any
	if err := toml.Unmarshal(data, &doc); err != nil {
		var de *toml.DecodeError
		if errors.As(err, &de) {
			row, _ := de.Position()
			return Wiring{}, fmt.Errorf("wiring line %d: %v", row, de)
		}
		return Wiring{}, fmt.Errorf("wiring: %v", err)
	}
	lines, err := keyLines(data)
	if err != nil {
		return Wiring{}, fmt.Errorf("wiring: %v", err)
	}
	line := func(path ...string) int { return lines[strings.Join(path, "\x00")] }
	var w Wiring
	for _, k := range sortedKeys(doc) {
		if k != "instances" && k != "wires" {
			return Wiring{}, fmt.Errorf("wiring line %d: no key %s: a wiring holds [instances] and [wires]", line(k), k)
		}
	}
	instances, err := table(doc, "instances", line("instances"))
	if err != nil {
		return Wiring{}, err
	}
	for name, v := range instances {
		at := line("instances", name)
		t, ok := v.(map[string]any)
		if !ok {
			return Wiring{}, fmt.Errorf("wiring line %d: instance %s is no table", at, name)
		}
		in := Instance{Name: name, Enabled: true, Config: map[string]ConfigValue{}, Line: at}
		for _, k := range sortedKeys(t) {
			kl := line("instances", name, k)
			switch k {
			case "component":
				s, ok := t[k].(string)
				if !ok || s == "" {
					return Wiring{}, fmt.Errorf("wiring line %d: instance %s: component is no name", kl, name)
				}
				in.Component = s
			case "enabled":
				b, ok := t[k].(bool)
				if !ok {
					return Wiring{}, fmt.Errorf("wiring line %d: instance %s: enabled is true or false", kl, name)
				}
				in.Enabled = b
				if !b {
					in.OffLine = kl
				}
			case "config":
				cfg, ok := t[k].(map[string]any)
				if !ok {
					return Wiring{}, fmt.Errorf("wiring line %d: instance %s: config is no table", kl, name)
				}
				for key, v := range cfg {
					in.Config[key] = ConfigValue{Value: v, Line: line("instances", name, "config", key)}
				}
			default:
				return Wiring{}, fmt.Errorf("wiring line %d: instance %s: no key %s: an instance holds component, enabled and config", kl, name, k)
			}
		}
		if in.Component == "" {
			return Wiring{}, fmt.Errorf("wiring line %d: instance %s names no component", at, name)
		}
		w.Instances = append(w.Instances, in)
	}
	wires, err := table(doc, "wires", line("wires"))
	if err != nil {
		return Wiring{}, err
	}
	for port, v := range wires {
		wr := Wire{Port: port, Line: line("wires", port)}
		switch t := v.(type) {
		case string:
			wr.To = t
		case map[string]any:
			for _, k := range sortedKeys(t) {
				switch k {
				case "to":
					wr.To, _ = t[k].(string)
				case "builtin":
					b, ok := t[k].(bool)
					if !ok {
						return Wiring{}, fmt.Errorf("wiring line %d: wire %s: builtin is true or false", wr.Line, port)
					}
					wr.Builtin = b
				default:
					return Wiring{}, fmt.Errorf("wiring line %d: wire %s: no key %s: a wire holds to and builtin", wr.Line, port, k)
				}
			}
		}
		if wr.To == "" {
			return Wiring{}, fmt.Errorf("wiring line %d: wire %s binds to no name, port, verb or %s", wr.Line, port, BuiltIn)
		}
		w.Wires = append(w.Wires, wr)
	}
	sort.Slice(w.Instances, func(i, j int) bool { return w.Instances[i].Line < w.Instances[j].Line })
	sort.Slice(w.Wires, func(i, j int) bool { return w.Wires[i].Line < w.Wires[j].Line })
	return w, nil
}

// table answers the table doc holds under key, or none where it holds none.
func table(doc map[string]any, key string, line int) (map[string]any, error) {
	v, ok := doc[key]
	if !ok {
		return nil, nil
	}
	t, ok := v.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("wiring line %d: %s is no table", line, key)
	}
	return t, nil
}

// keyLines answers the line each key path first stands on, its segments
// joined by NUL: a table header's, a key's, or a key's inside an inline table.
func keyLines(data []byte) (map[string]int, error) {
	p := &unstable.Parser{}
	p.Reset(data)
	kl := &keyLiner{lines: map[string]int{}}
	for i, c := range data {
		if c == '\n' {
			kl.breaks = append(kl.breaks, i)
		}
	}
	var tablePath []string
	for p.NextExpression() {
		e := p.Expression()
		switch e.Kind {
		case unstable.Table, unstable.ArrayTable:
			tablePath = kl.path(e.Key(), nil)
		case unstable.KeyValue:
			kl.keyValue(e, tablePath)
		}
	}
	return kl.lines, p.Error()
}

// keyLiner records the line of each key path: breaks are the offsets of the
// file's line breaks, so a key's line is one more than the breaks before it.
type keyLiner struct {
	breaks []int
	lines  map[string]int
}

func (kl *keyLiner) keyValue(kv *unstable.Node, under []string) {
	path := kl.path(kv.Key(), under)
	if v := kv.Value(); v.Kind == unstable.InlineTable {
		for it := v.Children(); it.Next(); {
			if n := it.Node(); n.Kind == unstable.KeyValue {
				kl.keyValue(n, path)
			}
		}
	}
}

// path answers the path a dotted key makes under a path, and records the line of each new prefix.
func (kl *keyLiner) path(it unstable.Iterator, under []string) []string {
	path := append([]string{}, under...)
	for it.Next() {
		k := it.Node()
		path = append(path, string(k.Data))
		joined := strings.Join(path, "\x00")
		if _, seen := kl.lines[joined]; !seen {
			kl.lines[joined] = sort.SearchInts(kl.breaks, int(k.Raw.Offset)) + 1
		}
	}
	return path
}

var durationType = reflect.TypeFor[time.Duration]()

// configValue converts a config value as TOML reads it into the key's type: a
// duration from a string such as "2m", a struct from a table by its fields' toml tags or names.
func configValue(v any, t reflect.Type) (any, error) {
	x, err := convert(v, t)
	if err != nil {
		return nil, err
	}
	return x.Interface(), nil
}

func convert(v any, t reflect.Type) (reflect.Value, error) {
	out := reflect.New(t).Elem()
	if t == durationType {
		s, ok := v.(string)
		if !ok {
			return out, fmt.Errorf("a duration is a string such as \"2m\", not %T", v)
		}
		d, err := time.ParseDuration(s)
		if err != nil {
			return out, err
		}
		out.SetInt(int64(d))
		return out, nil
	}
	switch t.Kind() {
	case reflect.Interface:
		if v != nil && !reflect.TypeOf(v).AssignableTo(t) {
			return out, fmt.Errorf("%T is no %s", v, t)
		}
		if v != nil {
			out.Set(reflect.ValueOf(v))
		}
	case reflect.Bool:
		b, ok := v.(bool)
		if !ok {
			return out, fmt.Errorf("%v is no bool", v)
		}
		out.SetBool(b)
	case reflect.String:
		s, ok := v.(string)
		if !ok {
			return out, fmt.Errorf("%v is no string", v)
		}
		out.SetString(s)
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		n, ok := v.(int64)
		if !ok || out.OverflowInt(n) {
			return out, fmt.Errorf("%v is no %s", v, t)
		}
		out.SetInt(n)
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		n, ok := v.(int64)
		if !ok || n < 0 || out.OverflowUint(uint64(n)) {
			return out, fmt.Errorf("%v is no %s", v, t)
		}
		out.SetUint(uint64(n))
	case reflect.Float32, reflect.Float64:
		switch n := v.(type) {
		case float64:
			out.SetFloat(n)
		case int64:
			out.SetFloat(float64(n))
		default:
			return out, fmt.Errorf("%v is no number", v)
		}
	case reflect.Slice:
		items, ok := v.([]any)
		if !ok {
			return out, fmt.Errorf("%v is no array", v)
		}
		out = reflect.MakeSlice(t, len(items), len(items))
		for i, item := range items {
			x, err := convert(item, t.Elem())
			if err != nil {
				return out, fmt.Errorf("item %d: %w", i+1, err)
			}
			out.Index(i).Set(x)
		}
	case reflect.Map:
		m, ok := v.(map[string]any)
		if !ok || t.Key().Kind() != reflect.String {
			return out, fmt.Errorf("%v is no table of %s", v, t)
		}
		out = reflect.MakeMapWithSize(t, len(m))
		for _, k := range sortedKeys(m) {
			x, err := convert(m[k], t.Elem())
			if err != nil {
				return out, fmt.Errorf("%s: %w", k, err)
			}
			out.SetMapIndex(reflect.ValueOf(k).Convert(t.Key()), x)
		}
	case reflect.Struct:
		m, ok := v.(map[string]any)
		if !ok {
			return out, fmt.Errorf("%v is no table", v)
		}
		for _, k := range sortedKeys(m) {
			f, ok := fieldOf(t, k)
			if !ok {
				return out, fmt.Errorf("%s has no field %s", t, k)
			}
			x, err := convert(m[k], f.Type)
			if err != nil {
				return out, fmt.Errorf("%s: %w", k, err)
			}
			out.FieldByIndex(f.Index).Set(x)
		}
	default:
		return out, fmt.Errorf("a config key of type %s cannot be given in the wiring", t)
	}
	return out, nil
}

// fieldOf answers the exported field of t a table key names: by its toml tag, or by its name in any case.
func fieldOf(t reflect.Type, key string) (reflect.StructField, bool) {
	for i := range t.NumField() {
		f := t.Field(i)
		if !f.IsExported() {
			continue
		}
		if tag, _, _ := strings.Cut(f.Tag.Get("toml"), ","); tag == key || (tag == "" && strings.EqualFold(f.Name, key)) {
			return f, true
		}
	}
	return reflect.StructField{}, false
}

// splitPort splits instance.port; ok is false where s is no port of a known instance.
func splitPort(s string, known map[string]*instance) (inst, port string, ok bool) {
	inst, port, ok = strings.Cut(s, ".")
	if !ok || known[inst] == nil {
		return "", "", false
	}
	return inst, port, true
}
