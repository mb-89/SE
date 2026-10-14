package index

import (
	_ "embed"
	"fmt"
	"reflect"
	"strings"

	"gopkg.in/yaml.v3"
)

// BuiltIn is what a wire names to leave an input unbound: it reads its type's zero value.
const BuiltIn = "built-in"

// Wiring is the wiring file: the module instances and the wires that bind
// their ports. It is the only place that knows the global layout.
//
//	instances:
//	  counter: {module: counter, config: {step: 2}}
//	  report: {module: report}
//	  issues/pull: {module: issues/pull}  # nested: it owns the names issues/pull/...
//	wires:
//	  counter.count: numbers/count   # an output to a name
//	  report.total: counter.count    # an input to another instance's port
//	  report.extra: built-in         # an input left unbound
type Wiring struct {
	Instances []Instance
	Wires     []Wire
}

// Instance is one module instance: its name, plain or nested as <cluster>/<module>, its module, and the config values the wiring gives it.
type Instance struct {
	Name, Module string
	Config       map[string]*yaml.Node
	Line         int
}

// Wire binds a port, instance.port, to a name, another instance's port, or BuiltIn.
type Wire struct {
	Port, To string
	Line     int
}

// WiringFile is where the wiring file stands, relative to a checkout: a
// value set there on main reaches a running box, which reads it from
// origin/main before it takes anything.
const WiringFile = "src/index/wiring.yaml"

// wired is the wiring file the se binary carries.
//
//go:embed wiring.yaml
var wired []byte

// Wired answers the wiring file the se binary was built with.
func Wired() (Wiring, error) { return ParseWiring(wired) }

// ParseWiring reads a wiring file.
func ParseWiring(data []byte) (Wiring, error) {
	var doc struct {
		Instances yaml.Node `yaml:"instances"`
		Wires     yaml.Node `yaml:"wires"`
	}
	if err := yaml.Unmarshal(data, &doc); err != nil {
		return Wiring{}, fmt.Errorf("wiring: %v", err)
	}
	var w Wiring
	err := eachPair(&doc.Instances, func(k, v *yaml.Node) error {
		var in struct {
			Module string               `yaml:"module"`
			Config map[string]yaml.Node `yaml:"config"`
		}
		if err := v.Decode(&in); err != nil {
			return fmt.Errorf("wiring line %d: instance %s: %v", k.Line, k.Value, err)
		}
		if in.Module == "" {
			return fmt.Errorf("wiring line %d: instance %s names no module", k.Line, k.Value)
		}
		inst := Instance{Name: k.Value, Module: in.Module, Config: map[string]*yaml.Node{}, Line: k.Line}
		for key, node := range in.Config {
			inst.Config[key] = &node
		}
		w.Instances = append(w.Instances, inst)
		return nil
	})
	if err != nil {
		return Wiring{}, err
	}
	err = eachPair(&doc.Wires, func(k, v *yaml.Node) error {
		if v.Kind != yaml.ScalarNode || v.Value == "" {
			return fmt.Errorf("wiring line %d: wire %s binds to no name, port or %s", k.Line, k.Value, BuiltIn)
		}
		w.Wires = append(w.Wires, Wire{Port: k.Value, To: v.Value, Line: k.Line})
		return nil
	})
	return w, err
}

// eachPair calls f on each key and value of a mapping; an absent one has none.
func eachPair(n *yaml.Node, f func(k, v *yaml.Node) error) error {
	if n.Kind == 0 {
		return nil
	}
	if n.Kind != yaml.MappingNode {
		return fmt.Errorf("wiring line %d: a mapping is expected", n.Line)
	}
	for i := 0; i+1 < len(n.Content); i += 2 {
		if err := f(n.Content[i], n.Content[i+1]); err != nil {
			return err
		}
	}
	return nil
}

// configValue decodes a config value the wiring gives into the key's type.
func configValue(node *yaml.Node, t reflect.Type) (any, error) {
	v := reflect.New(t)
	if err := node.Decode(v.Interface()); err != nil {
		return nil, err
	}
	return v.Elem().Interface(), nil
}

// splitPort splits instance.port; ok is false where s is no port of a known instance.
func splitPort(s string, known map[string]*instance) (inst, port string, ok bool) {
	inst, port, ok = strings.Cut(s, ".")
	if !ok || known[inst] == nil {
		return "", "", false
	}
	return inst, port, true
}
