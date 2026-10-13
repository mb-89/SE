package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
)

// The help reads at a glance: the overview gives each command one short line
// under its group's heading, and se help <command> gives one command's usage,
// what it does, and every flag it takes, one per line. Both are made from the
// registry. A session shows them as a fenced block in its transcript, so the
// columns stay aligned; a terminal colours headings and names.

// width is how wide a help line may be.
const width = 80

func init() {
	register(Command{
		Name:    "help",
		Usage:   "help [<command>]",
		Group:   "Session",
		Summary: "list the commands, or show one: help <command>",
		Details: "Without a word, help lists every command under its group. " +
			"With a command's name, it shows that command's usage and every flag it takes; " +
			"se <command> --help shows the same.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			name := strings.Join(c.Args, " ")
			switch name {
			case "":
				return Reply{Text: help(c.Session, c.Color)}, nil
			case "-h", "-help", "--help":
				return Reply{}, flag.ErrHelp
			}
			if cmd, ok := commands[name]; ok && (cmd.Session || !c.Session) {
				return Reply{Text: commandHelp(cmd, flagsOf(cmd, c.Session), c.Session, c.Color)}, nil
			}
			if under := under(name, c.Session); len(under) > 0 {
				return Reply{Text: fenced(listing(under, c.Session, c.Color), c.Session)}, nil
			}
			return Reply{}, fmt.Errorf("se has no command %q; %s help lists them", name, prog(c.Session))
		},
	})
}

// help is the overview: every command a terminal (session false) or a session
// can run, one line each, under its group's heading.
func help(session, color bool) string {
	prog := prog(session)
	var b strings.Builder
	fmt.Fprintf(&b, "%s <command> [flags]\n\n", prog)
	b.WriteString(listing(offered(session), session, color))
	fmt.Fprintf(&b, "\n\n%s help <command> shows its usage and flags.", prog)
	if !session {
		b.WriteString("\nEvery command takes --workspace DIR (default: here).")
	}
	return fenced(b.String(), session)
}

// listing is the commands under their groups' headings, the groups in
// alphabetical order, each command a name and its summary in two columns.
func listing(cmds []Command, session, color bool) string {
	groups := map[string][]Command{}
	pad := 0
	for _, c := range cmds {
		groups[c.Group] = append(groups[c.Group], c)
		pad = max(pad, len(c.Name))
	}
	names := make([]string, 0, len(groups))
	for g := range groups {
		names = append(names, g)
	}
	sort.Strings(names)
	var lines []string
	for i, g := range names {
		if i > 0 {
			lines = append(lines, "")
		}
		heading := g
		if heading == "" {
			heading = "Other"
		}
		lines = append(lines, paint(heading+":", bold, color))
		for _, c := range groups[g] {
			name := paint(c.Name, cyan, color) + strings.Repeat(" ", pad-len(c.Name))
			lines = append(lines, "  "+name+"  "+c.Summary)
		}
	}
	return strings.Join(lines, "\n")
}

// commandHelp is one command's help: its usage, what it does, and the flags
// of fs, the flag set its Run made, one per line.
func commandHelp(c Command, fs *flag.FlagSet, session, color bool) string {
	var b strings.Builder
	b.WriteString(strings.TrimPrefix(wrap(prog(session)+" "+c.Usage, width, "    "), "    ") + "\n\n")
	about := c.Summary
	if c.Details != "" {
		about = c.Details
	}
	b.WriteString(wrap(capital(about), width, ""))
	type row struct{ name, usage string }
	var rows []row
	pad := 0
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
			rows = append(rows, row{name, usage})
			pad = max(pad, len(name))
		})
	}
	if len(rows) > 0 {
		fmt.Fprintf(&b, "\n\n%s", paint("Flags:", bold, color))
		indent := strings.Repeat(" ", 2+pad+2)
		for _, r := range rows {
			name := paint(r.name, cyan, color) + strings.Repeat(" ", pad-len(r.name))
			fmt.Fprintf(&b, "\n  %s  %s", name, strings.TrimPrefix(wrap(r.usage, width, indent), indent))
		}
	}
	return fenced(b.String(), session)
}

// flagsOf is the flag set a command takes, read by running it with --help:
// every command parses its flags before it does anything.
func flagsOf(c Command, session bool) *flag.FlagSet {
	call := &Call{Args: []string{"--help"}, Workspace: ".", Session: session}
	if _, err := c.Run(call); err != nil && call.flags != nil {
		return call.flags
	}
	return nil
}

// under lists the commands whose name starts with the words of first.
func under(first string, session bool) []Command {
	var out []Command
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
// as written, aligned; a terminal's help stands as it is.
func fenced(text string, session bool) string {
	if !session {
		return text
	}
	return "```\n" + text + "\n```"
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
