package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/issues"
)

// The help reads at a glance: the overview gives each command one short line
// under its group's heading, and se help <command> gives one command's usage,
// what it does, and every flag it takes, one per line. Both are made from the
// registry, first as data (Help), then as text from that data. A session's
// answer carries both: the plugin draws the data as a layout, and the text,
// which the model reads, keeps its columns in a fenced block. A terminal
// colours headings and names.

// width is how wide a help line may be.
const width = 80

// Help is the help as data, which the plugin draws in a session.
type Help struct {
	// Usage is the command line: prog and the command's usage, or for the
	// overview prog <command> [flags]. Empty for a list of sub-words.
	Usage string `json:"usage,omitempty"`
	// About is what one command does.
	About string `json:"about,omitempty"`
	// Groups are the commands listed, under their headings.
	Groups []HelpGroup `json:"groups,omitempty"`
	// Flags are the flags one command takes.
	Flags []HelpFlag `json:"flags,omitempty"`
	// Note is the closing line of the overview.
	Note string `json:"note,omitempty"`
}

// HelpGroup is one heading of a listing and the commands under it, by name.
type HelpGroup struct {
	Name     string        `json:"name"`
	Commands []HelpCommand `json:"commands"`
}

// HelpCommand is one command of a listing.
type HelpCommand struct {
	Name    string `json:"name"`
	Summary string `json:"summary"`
	Usage   string `json:"usage"`
}

// HelpFlag is one flag a command takes: its name with its kind, and what it does.
type HelpFlag struct {
	Name  string `json:"name"`
	Usage string `json:"usage"`
}

func init() {
	register(Command{
		Name:    "help",
		Class:   interactive,
		Usage:   "help [<command>]",
		Group:   "Session",
		Summary: "list the commands, or show one: help <command>",
		Details: []string{
			"Without a word, help lists every command under its group.",
			"With a command's name, it shows that command's usage and every flag it takes; se <command> --help shows the same.",
		},
		Session: true,
		Run: func(c *Call) (Reply, error) {
			name := strings.Join(c.Args, " ")
			switch name {
			case "":
				return helpReply(overview(c.Session), c.Session, c.Color), nil
			case "-h", "-help", "--help":
				return Reply{}, flag.ErrHelp
			}
			if cmd, ok := catalog().Command(name); ok && (cmd.Session || !c.Session) {
				return helpReply(commandHelpOf(cmd, flagsOf(cmd.Name, c.Session), c.Session), c.Session, c.Color), nil
			}
			if under := under(name, c.Session); len(under) > 0 {
				return helpReply(Help{Groups: groupsOf(under, c.Session)}, c.Session, c.Color), nil
			}
			return Reply{}, fmt.Errorf("se has no command %q; %s help lists them", name, prog(c.Session))
		},
	})
}

// helpReply answers the help: its text, and in a session the data beside it.
func helpReply(h Help, session, color bool) Reply {
	r := Reply{Text: helpText(h, session, color)}
	if session {
		r.Help = &h
	}
	return r
}

// help is the overview's text: every command a terminal (session false) or a
// session can run, one line each, under its group's heading.
func help(session, color bool) string {
	return helpText(overview(session), session, color)
}

// overview is the overview as data.
func overview(session bool) Help {
	prog := prog(session)
	note := prog + " help <command> shows its usage and flags.\n" + agentsNote()
	if !session {
		note += "\nEvery command takes --workspace DIR (default: here)."
	}
	return Help{Usage: prog + " <command> [flags]", Groups: groupsOf(offered(session), session), Note: note}
}

// agentsNote names the plugin's agents, from the registry of kinds, and how
// a person reaches one.
func agentsNote() string {
	var types []string
	for _, k := range issues.IssueKinds {
		types = append(types, k.Type())
	}
	return "The agents, each reached as @agent-<name> or by asking for its role:\n" + strings.Join(types, ", ") + "."
}

// groupsOf puts the commands under their groups' headings, the groups in
// alphabetical order, the commands in the order given.
func groupsOf(cmds []index.CommandInfo, session bool) []HelpGroup {
	byName := map[string]*HelpGroup{}
	var names []string
	for _, c := range cmds {
		heading := c.Group
		g, ok := byName[heading]
		if !ok {
			g = &HelpGroup{Name: heading}
			byName[heading] = g
			names = append(names, heading)
		}
		g.Commands = append(g.Commands, HelpCommand{Name: c.Name, Summary: c.Summary, Usage: prog(session) + " " + c.Usage})
	}
	sort.Strings(names)
	out := make([]HelpGroup, 0, len(names))
	for _, n := range names {
		out = append(out, *byName[n])
	}
	return out
}

// commandHelpOf is one command's help as data.
func commandHelpOf(c index.CommandInfo, fs *flag.FlagSet, session bool) Help {
	h := Help{Usage: prog(session) + " " + c.Usage, About: capital(c.Help)}
	if fs != nil {
		fs.VisitAll(func(f *flag.Flag) {
			kind, usage := flag.UnquoteUsage(f)
			name := "--" + f.Name
			if kind != "" {
				name += " " + kind
			}
			if f.Name != "workspace" && f.DefValue != "" && f.DefValue != "false" && f.DefValue != "0" {
				usage += fmt.Sprintf(" (default: %s)", f.DefValue)
			}
			h.Flags = append(h.Flags, HelpFlag{Name: name, Usage: usage})
		})
	}
	return h
}

// helpText is the help as text: its parts a blank line apart, the names of
// commands and of flags in a column of their own.
func helpText(h Help, session, color bool) string {
	var parts []string
	if h.Usage != "" {
		parts = append(parts, strings.TrimPrefix(wrap(h.Usage, width, "    "), "    "))
	}
	if h.About != "" {
		parts = append(parts, wrap(h.About, width, ""))
	}
	if len(h.Groups) > 0 {
		parts = append(parts, listing(h.Groups, color))
	}
	if len(h.Flags) > 0 {
		pad := 0
		for _, f := range h.Flags {
			pad = max(pad, len(f.Name))
		}
		lines := []string{paint("Flags:", bold, color)}
		indent := strings.Repeat(" ", 2+pad+2)
		for _, f := range h.Flags {
			name := paint(f.Name, cyan, color) + strings.Repeat(" ", pad-len(f.Name))
			lines = append(lines, "  "+name+"  "+strings.TrimPrefix(wrap(f.Usage, width, indent), indent))
		}
		parts = append(parts, strings.Join(lines, "\n"))
	}
	if h.Note != "" {
		parts = append(parts, h.Note)
	}
	return fenced(strings.Join(parts, "\n\n"), session)
}

// listing is the groups under their headings, each command a name and its
// summary in two columns.
func listing(groups []HelpGroup, color bool) string {
	pad := 0
	for _, g := range groups {
		for _, c := range g.Commands {
			pad = max(pad, len(c.Name))
		}
	}
	var lines []string
	for i, g := range groups {
		if i > 0 {
			lines = append(lines, "")
		}
		lines = append(lines, paint(g.Name+":", bold, color))
		for _, c := range g.Commands {
			name := paint(c.Name, cyan, color) + strings.Repeat(" ", pad-len(c.Name))
			lines = append(lines, "  "+name+"  "+c.Summary)
		}
	}
	return strings.Join(lines, "\n")
}

// flagsOf is the flag set the command name takes, read by running it with
// --help: every command parses its flags before it does anything.
func flagsOf(name string, session bool) *flag.FlagSet {
	call := &Call{Args: []string{"--help"}, Workspace: ".", Session: session}
	if _, err := runCommand(name, call); err != nil && call.flags != nil {
		return call.flags
	}
	return nil
}

// under lists the commands whose name starts with the words of first.
func under(first string, session bool) []index.CommandInfo {
	var out []index.CommandInfo
	for _, c := range offered(session) {
		if first != "" && strings.HasPrefix(c.Name, first+" ") {
			out = append(out, c)
		}
	}
	return out
}

// unknown is what se answers to a word it has no command for.
func unknown(name string, session, color bool) string {
	return fmt.Sprintf("%s\n\nse has no command %q.", help(session, color), name)
}

// fenced puts a session's help in a fenced block, which the transcript shows
// as written, aligned; a terminal's help stands as it is. The first paragraph
// (the usage), or the first line where there is one paragraph, stays out of
// the block: the transcript puts "se: " before the first line, and a fence
// there is no fence, only three backticks shown as text.
func fenced(text string, session bool) string {
	if !session {
		return text
	}
	head, body, ok := strings.Cut(text, "\n\n")
	if !ok {
		if head, body, ok = strings.Cut(text, "\n"); !ok {
			return text
		}
	}
	return head + "\n```\n" + body + "\n```"
}

// wrap breaks text into lines of at most width, each after the first indented.
func wrap(text string, width int, indent string) string {
	var lines []string
	line := indent
	for _, word := range strings.Fields(text) {
		if strings.TrimSpace(line) != "" && len(line)+1+len(word) > width {
			lines = append(lines, line)
			line = indent
		}
		if strings.TrimSpace(line) != "" {
			line += " "
		}
		line += word
	}
	return strings.Join(append(lines, line), "\n")
}

// capital starts a sentence with a capital letter.
func capital(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

const (
	bold = "1"
	cyan = "36"
)

// paint colours s when color is set.
func paint(s, code string, color bool) string {
	if !color {
		return s
	}
	return "\x1b[" + code + "m" + s + "\x1b[0m"
}

// colors says whether what goes to w may be coloured: w is a terminal, and
// NO_COLOR is unset.
func colors(w io.Writer) bool {
	f, ok := w.(*os.File)
	if !ok || os.Getenv("NO_COLOR") != "" {
		return false
	}
	info, err := f.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}
