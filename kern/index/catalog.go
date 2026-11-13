package index

import "sort"

// Catalog is the collector: every instance's ports, config, request ports and
// verbs, and every command, as the components declared them and the wiring
// binds them. It is a manifest: it holds what components declared and adds no
// text of its own. Every surface (the command line, the help, the agent's
// command list) renders it.
type Catalog struct {
	Instances []InstanceInfo
	Commands  []CommandInfo
}

// InstanceInfo is one instance as the catalog shows it.
type InstanceInfo struct {
	Name, Component, Help string
	// IO is set on an instance of a component that carries the I/O flag.
	IO bool
	// Enabled is false on an instance the wiring switches off: its names read
	// their built-in values, and its commands are offered nowhere.
	Enabled  bool
	Inputs   []PortInfo
	Outputs  []PortInfo
	Config   []PortInfo
	Requests []RequestInfo
	Verbs    []VerbDecl
}

// PortInfo is one port and the name the wiring binds it to; an input left
// built-in has none.
type PortInfo struct {
	Port
	Name string
}

// RequestInfo is one request port and the verb, instance.verb, the wiring binds it to.
type RequestInfo struct {
	RequestDecl
	Verb string
}

// CommandInfo is one command and the instance that answers it.
type CommandInfo struct {
	CommandDecl
	Instance string
}

// Command answers the command of that name.
func (c Catalog) Command(name string) (CommandInfo, bool) {
	i := sort.Search(len(c.Commands), func(i int) bool { return c.Commands[i].Name >= name })
	if i < len(c.Commands) && c.Commands[i].Name == name {
		return c.Commands[i], true
	}
	return CommandInfo{}, false
}

// Session answers the commands offered to the agent.
func (c Catalog) Session() []CommandInfo {
	var out []CommandInfo
	for _, ci := range c.Commands {
		if ci.Session {
			out = append(out, ci)
		}
	}
	return out
}

// catalog gathers what every instance declared; it refuses two commands of
// one name among the switched-on instances, and offers no command of a
// switched-off one.
func (b *builder) catalog() Catalog {
	var c Catalog
	owner := map[string]string{}
	for _, name := range sortedKeys(b.ix.insts) {
		in := b.ix.insts[name]
		info := InstanceInfo{Name: name, Component: in.comp.Name(), Help: in.comp.Help(), IO: in.comp.IO(), Enabled: in.enabled, Verbs: in.comp.Verbs()}
		for _, p := range in.comp.Inputs() {
			info.Inputs = append(info.Inputs, PortInfo{Port: p, Name: in.in[p.Port]})
		}
		for _, p := range in.comp.Outputs() {
			info.Outputs = append(info.Outputs, PortInfo{Port: p, Name: in.out[p.Port]})
		}
		for _, p := range in.comp.Config() {
			info.Config = append(info.Config, PortInfo{Port: p, Name: in.in[ConfigPrefix+p.Port]})
		}
		for _, r := range in.comp.Requests() {
			verb := ""
			if t, ok := in.req[r.Port]; ok {
				verb = t.inst + "." + t.verb
			}
			info.Requests = append(info.Requests, RequestInfo{RequestDecl: r, Verb: verb})
		}
		c.Instances = append(c.Instances, info)
		if !in.enabled {
			continue
		}
		for _, d := range in.comp.Commands() {
			if first, taken := owner[d.Name]; taken {
				b.fail(in.line, "command %q is declared by %s and %s", d.Name, first, name)
				continue
			}
			owner[d.Name] = name
			c.Commands = append(c.Commands, CommandInfo{CommandDecl: d, Instance: name})
		}
	}
	sort.Slice(c.Commands, func(i, j int) bool { return c.Commands[i].Name < c.Commands[j].Name })
	return c
}
