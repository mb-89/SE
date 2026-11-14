// Package mcp is kern's MCP door: `<name> mcp`, an MCP server over stdio that
// offers the core's read-only commands (index.CommandDecl.ReadOnly) to an
// agent host as a few coarse tools, generated from the catalog
// (index.Catalog), never written per tool.
//
// A host spawns its configured stdio servers as a session starts, so the door
// answers initialize and tools/list at once, from the catalog it reads without
// the core (host.Catalog), and starts the core detached, or attaches to the one
// that runs, in the background. It holds a session lease for as long as the
// connection lives and returns it on EOF (kern/README.md "The MCP door").
package mcp

import (
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/mb-89/kern/index"
)

// The door's own tools, beside one per instance that offers read-only commands.
const (
	// StatusTool says whether the core runs and its health.
	StatusTool = "status"
	// GreetingTool answers the application's greeting: the names and
	// commands it names (Options.Greeting).
	GreetingTool = "greeting"
)

// Tool is one tool the door offers, as the catalog makes it.
type Tool struct {
	Name, Title, Description string
	// Instance is the instance a command tool runs the commands of; empty for
	// the door's own tools.
	Instance string
	// Commands are the read-only commands a command tool runs, by name; empty
	// for the door's own tools.
	Commands []index.CommandInfo
	// Greeting are the greeting tool's entries: each a name or a command.
	Greeting []Entry
	// OpenWorld is set where the tool may read outside services: every
	// tool that runs a component's command.
	OpenWorld bool
}

// Entry is one part of the greeting: a name the catalog's instances write,
// or a read-only command it runs without arguments.
type Entry struct {
	Name    string
	Command bool
	Help    string
}

var toolName = regexp.MustCompile(`^[a-z0-9_]{1,64}$`)

// ToolName is an instance's tool name, in snake_case as hosts name tools:
// its dashes read as underscores.
func ToolName(instance string) string { return strings.ReplaceAll(instance, "-", "_") }

// Tools answers the door's tools for the catalog: status, the greeting where
// the application names one, and one tool per switched-on instance that
// offers read-only commands (index.CommandDecl.ReadOnly), named after the
// instance in snake_case (ToolName). A command that is not declared
// read-only is in no tool, whatever its class.
//
// It is the door's catalog check: it refuses a read-only command without an
// MCP description (index.CommandDecl.MCP), an instance whose tool name is
// none or takes one of the door's own, and a greeting entry that is a
// command not declared read-only. A greeting entry the catalog lacks is left
// out, so a checkout that wires less greets with less.
func Tools(app string, c index.Catalog, greeting []string) ([]Tool, error) {
	var errs []string
	enabled := map[string]index.InstanceInfo{}
	outputs := map[string]index.PortInfo{}
	for _, in := range c.Instances {
		if !in.Enabled {
			continue
		}
		enabled[in.Name] = in
		for _, out := range in.Outputs {
			if out.Name != "" && !out.Family {
				outputs[out.Name] = out
			}
		}
	}
	byInstance := map[string][]index.CommandInfo{}
	for _, ci := range c.Commands {
		if !ci.ReadOnly {
			continue
		}
		if strings.TrimSpace(ci.MCP) == "" {
			errs = append(errs, fmt.Sprintf("command %q of instance %s is read-only and has no mcp description", ci.Name, ci.Instance))
			continue
		}
		byInstance[ci.Instance] = append(byInstance[ci.Instance], ci)
	}
	tools := []Tool{{
		Name: StatusTool, Title: app + " status",
		Description: fmt.Sprintf("Whether %s's core runs in this checkout, and its health: pid, bus, the sessions holding a lease, the instances and the placed processes. "+
			"Use it when another tool of this server answers \"starting\" or fails, or to see what the core carries; it never starts anything the door has not.", app),
	}}
	var entries []Entry
	for _, e := range greeting {
		if out, ok := outputs[e]; ok {
			entries = append(entries, Entry{Name: e, Help: out.Help})
			continue
		}
		if ci, ok := c.Command(e); ok {
			if _, on := enabled[ci.Instance]; !on {
				continue
			}
			if !ci.ReadOnly {
				errs = append(errs, fmt.Sprintf("greeting entry %q is a command not declared read-only: the greeting only reads", e))
				continue
			}
			entries = append(entries, Entry{Name: e, Command: true, Help: ci.MCP})
		}
	}
	if len(entries) > 0 {
		var b strings.Builder
		fmt.Fprintf(&b, "%s's start greeting, live from its core: what is due and what is queued. Use it at the start of a session, and whenever you ask what to do next. It reads:", app)
		for _, e := range entries {
			fmt.Fprintf(&b, "\n- `%s`: %s", e.Name, strings.TrimSpace(e.Help))
		}
		tools = append(tools, Tool{Name: GreetingTool, Title: app + " greeting", Description: b.String(), Greeting: entries, OpenWorld: true})
	}
	names := make([]string, 0, len(byInstance))
	for n := range byInstance {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		name := ToolName(n)
		if name == StatusTool || name == GreetingTool || !toolName.MatchString(name) {
			errs = append(errs, fmt.Sprintf("instance %s offers read-only commands, and %q is no tool name of its own: rename it in the wiring", n, name))
			continue
		}
		in := enabled[n]
		var b strings.Builder
		fmt.Fprintf(&b, "%s Runs one of its read-only commands, named in `command`, with `args` as its usage shows; it changes nothing. Use it:", strings.TrimSpace(in.Help))
		for _, ci := range byInstance[n] {
			fmt.Fprintf(&b, "\n- `%s`: %s Usage: `%s`", ci.Name, strings.TrimSpace(ci.MCP), oneLine(ci.Usage))
		}
		tools = append(tools, Tool{Name: name, Title: app + " " + n, Description: b.String(), Instance: n, Commands: byInstance[n], OpenWorld: true})
	}
	if len(errs) > 0 {
		return tools, fmt.Errorf("the MCP door's catalog check: %s", strings.Join(errs, "; "))
	}
	return tools, nil
}

// oneLine joins a usage argparse wrapped onto one line.
func oneLine(s string) string { return strings.Join(strings.Fields(s), " ") }
