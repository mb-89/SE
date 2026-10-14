package index

import "sort"

// Catalog is the collector: every instance's ports and config, and every
// command, as the modules declared them and the wiring binds them. It is a
// manifest: it holds what modules declared and adds no text of its own. Every
// adapter (the CLI, the plugin's /se, the /se ui buttons, the help) renders it.
type Catalog struct {
	Instances []InstanceInfo
	Commands  []CommandInfo
}

// InstanceInfo is one instance as the catalog shows it.
type InstanceInfo struct {
	Name, Module, Help string
	// IO is set on an instance of a module that carries the I/O flag.
	IO      bool
	Inputs  []PortInfo
	Outputs []PortInfo
	Config  []PortInfo
}

// PortInfo is one port and the name the wiring binds it to; an input left
// built-in has none.
type PortInfo struct {
	Port
	Name string
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

// Session answers the commands offered in a Claude session as /se <name>.
func (c Catalog) Session() []CommandInfo {
	return c.where(func(d CommandDecl) bool { return d.Session })
}

// Buttons answers the commands offered as /se ui buttons.
func (c Catalog) Buttons() []CommandInfo {
	return c.where(func(d CommandDecl) bool { return d.Button })
}

func (c Catalog) where(keep func(CommandDecl) bool) []CommandInfo {
	var out []CommandInfo
	for _, ci := range c.Commands {
		if keep(ci.CommandDecl) {
			out = append(out, ci)
		}
	}
	return out
}

// catalog gathers what every instance declared; it refuses two commands of one name.
func (b *builder) catalog() Catalog {
	var c Catalog
	owner := map[string]string{}
	for _, name := range sortedKeys(b.ix.insts) {
		in := b.ix.insts[name]
		info := InstanceInfo{Name: name, Module: in.mod.Name(), Help: in.mod.Help(), IO: in.mod.IO()}
		for _, p := range in.mod.Inputs() {
			info.Inputs = append(info.Inputs, PortInfo{Port: p, Name: in.in[p.Port]})
		}
		for _, p := range in.mod.Outputs() {
			info.Outputs = append(info.Outputs, PortInfo{Port: p, Name: in.out[p.Port]})
		}
		for _, p := range in.mod.Config() {
			info.Config = append(info.Config, PortInfo{Port: p, Name: in.in[ConfigPrefix+p.Port]})
		}
		c.Instances = append(c.Instances, info)
		for _, d := range in.mod.Commands() {
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
