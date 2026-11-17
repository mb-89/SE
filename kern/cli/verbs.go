package cli

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"text/tabwriter"
	"time"
)

// Verb is one command of the command line: the table of them (Add) drives
// Run's dispatch, the usage line, the unknown-verb message, the help and each
// verb's own -h.
type Verb struct {
	// Name is what a caller types after the application's name; Bare has none.
	Name string
	// Args is the arguments text the help and the verb's usage show.
	Args string
	// Doc is the one line the help shows beside it.
	Doc string
	// Hosts marks a verb that hosts and hooks call rather than a person.
	Hosts bool
	// Lead takes a first argument that is no flag before the flags (Call.Lead).
	Lead bool
	// FailOpen exits 0 instead of 2 where the flags do not parse: a hook's
	// exit code 2 is a block to its host.
	FailOpen bool
	// Exit is the verb's own exit codes, a line of the help; empty for kern's.
	Exit string
	// Flags declares the verb's flags on fs; nil for none.
	Flags func(fs *flag.FlagSet)
	// Run runs the verb once its flags parsed and answers the exit code.
	Run func(c *Call) int
}

// Call is one run of a verb: what it was called with.
type Call struct {
	Name   string // the application's name
	Verb   string
	Lead   string // the first argument of a Lead verb, where it was given
	Flags  *flag.FlagSet
	Stdin  io.Reader
	Stdout io.Writer
	Stderr io.Writer
}

// Args are the arguments after the flags, those after `--` included.
func (c *Call) Args() []string { return c.Flags.Args() }

func (c *Call) value(name string) any {
	return c.Flags.Lookup(name).Value.(flag.Getter).Get()
}

// String, Bool, Int and Duration read the flag of that name the verb declared.
func (c *Call) String(name string) string { return c.value(name).(string) }

func (c *Call) Bool(name string) bool { return c.value(name).(bool) }

func (c *Call) Int(name string) int { return c.value(name).(int) }

func (c *Call) Duration(name string) time.Duration { return c.value(name).(time.Duration) }

// About is the help's first line, what the application is: its main sets it
// before Run; empty prints none.
var About string

// Bare is what a run with no argument does, a Verb without a name: its Doc is
// the help's line for it and Run calls its Run. Where its Run is nil, a bare
// run prints the usage line on stderr and exits 2.
var Bare Verb

// exitCodes are kern's exit codes, the help's first line of them; a verb
// with codes of its own adds a line (Verb.Exit).
const exitCodes = "0 done, 1 no core runs (status), 2 a usage or start error"

// verbs is the table, kern's verbs first, then those the application added.
var verbs []Verb

func init() {
	verbs = []Verb{
		{Name: "help", Args: "[<verb>]", Doc: "print this help, or that verb's options (also --help, -h)", Run: runHelp},
		{Name: "start", Args: "[--root DIR] [--home DIR] [--grace D] [--idle D]", Hosts: true,
			Doc: "start the core in the background, return at once", Flags: coreFlags, Run: runStart},
		{Name: "status", Args: "[--root DIR] [--wait D] [--json]", Hosts: true,
			Doc: "say whether a core runs, and its health", Flags: statusFlags, Run: runStatus},
		{Name: "stop", Args: "[--root DIR]", Hosts: true,
			Doc: "stop the core and wait until it has exited", Flags: rootFlag, Run: runStop},
		{Name: "serve", Args: "[--root DIR] [--home DIR] [--grace D] [--idle D]", Hosts: true,
			Doc: "run the core in the foreground (what start spawns)", Flags: coreFlags, Run: runServe},
		{Name: "mcp", Args: "[--root DIR] [--home DIR] [--grace D] [--idle D] [--tools]", Hosts: true,
			Doc:   "the MCP door over stdio, starting the core or attaching to it; --tools prints its tools as JSON and exits",
			Flags: mcpFlags, Run: runMCP},
		{Name: "hook", Args: "<event> [--root DIR] [--wait D] [--unanswered N]", Hosts: true, Lead: true, FailOpen: true,
			Doc:   "post the host's hook JSON on stdin to the core and print its answer",
			Exit:  "0 and nothing printed where no core answers (a hook fails open), or N with --unanswered N where no command answered",
			Flags: hookFlags, Run: runHook},
	}
}

// Add adds an application's verb to the table; its main calls it before Run.
// A name the table already holds panics, naming both.
func Add(v Verb) {
	if v.Name == "" || v.Run == nil {
		panic(fmt.Sprintf("cli.Add: a verb needs a name and a run function (%q)", v.Name))
	}
	if had, ok := lookup(v.Name); ok {
		panic(fmt.Sprintf("cli.Add: the verb %q (%s) has the name of the table's %q (%s)", v.Name, v.Doc, had.Name, had.Doc))
	}
	verbs = append(verbs, v)
}

// Verbs are the table's verbs in order, a copy.
func Verbs() []Verb { return append([]Verb(nil), verbs...) }

func lookup(name string) (Verb, bool) {
	for _, v := range verbs {
		if v.Name == name {
			return v, true
		}
	}
	return Verb{}, false
}

// usageLine is the line the help, an unknown verb and a refused bare run show.
func usageLine(name string) string {
	return fmt.Sprintf("usage: %s [<verb>] [<options>]", name)
}

// Help writes the whole help of the command named name to w.
func Help(name string, w io.Writer) {
	if About != "" {
		fmt.Fprintln(w, About)
	}
	fmt.Fprintln(w, usageLine(name))
	fmt.Fprintln(w)
	tw := tabwriter.NewWriter(w, 0, 0, 3, ' ', 0)
	line := func(v Verb) { fmt.Fprintf(tw, "  %s\t%s\n", strings.TrimSpace(v.Name+" "+v.Args), v.Doc) }
	for _, v := range verbs {
		if !v.Hosts {
			line(v)
		}
	}
	if Bare.Run != nil {
		fmt.Fprintf(tw, "  (no verb)\t%s\n", Bare.Doc)
	}
	tw.Flush()
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Hosts and hooks call these:")
	for _, v := range verbs {
		if v.Hosts {
			line(v)
		}
	}
	tw.Flush()
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Exit codes:")
	fmt.Fprintf(tw, "  %s\t%s\n", "all", exitCodes)
	for _, v := range verbs {
		if v.Exit != "" {
			fmt.Fprintf(tw, "  %s\t%s\n", v.Name, v.Exit)
		}
	}
	tw.Flush()
	fmt.Fprintf(w, "\n%s <verb> -h prints that verb's options.\n", name)
}

// verbHelp writes one verb's usage, doc and flags to w.
func verbHelp(name string, v Verb, fs *flag.FlagSet, w io.Writer) {
	fmt.Fprintln(w, "usage: "+strings.TrimSpace(name+" "+v.Name+" "+v.Args))
	fmt.Fprintln(w, v.Doc)
	if v.Exit != "" {
		fmt.Fprintln(w, "exit codes: "+v.Exit)
	}
	out := fs.Output()
	fs.SetOutput(w)
	fs.PrintDefaults()
	fs.SetOutput(out)
}

// newFlags is the flag set of v, its flags declared, writing errors to stderr.
func newFlags(name string, v Verb, stderr io.Writer) *flag.FlagSet {
	fs := flag.NewFlagSet(strings.TrimSpace(name+" "+v.Name), flag.ContinueOnError)
	fs.SetOutput(stderr)
	fs.Usage = func() {}
	if v.Flags != nil {
		v.Flags(fs)
	}
	return fs
}

// call runs v with args, the arguments after its name.
func call(name string, v Verb, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	fs := newFlags(name, v, stderr)
	c := &Call{Name: name, Verb: v.Name, Flags: fs, Stdin: stdin, Stdout: stdout, Stderr: stderr}
	if v.Lead && len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		c.Lead, args = args[0], args[1:]
	}
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			verbHelp(name, v, fs, stdout)
			return 0
		}
		fmt.Fprintf(stderr, "usage: %s\n", strings.TrimSpace(name+" "+v.Name+" "+v.Args))
		if v.FailOpen {
			return 0
		}
		return 2
	}
	return v.Run(c)
}

// refuse says that name has no verb (none given where verb is empty) and
// answers 2.
func refuse(name, verb string, stderr io.Writer) int {
	if verb != "" {
		fmt.Fprintf(stderr, "%s: no command %q\n", name, verb)
	}
	fmt.Fprintln(stderr, usageLine(name))
	fmt.Fprintf(stderr, "%s help lists every verb\n", name)
	return 2
}

// Run is the command named name: it serves the components registered with
// index.Register before it is called, runs the verb args name from the table
// (Add), or Bare where none is given, and answers the exit code.
func Run(name string, args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		if Bare.Run == nil {
			return refuse(name, "", stderr)
		}
		return Bare.Run(&Call{Name: name, Flags: newFlags(name, Bare, stderr), Stdin: os.Stdin, Stdout: stdout, Stderr: stderr})
	}
	verb := args[0]
	if verb == "--help" || verb == "-h" || verb == "-help" {
		verb = "help"
	}
	v, ok := lookup(verb)
	if !ok {
		return refuse(name, verb, stderr)
	}
	return call(name, v, args[1:], os.Stdin, stdout, stderr)
}

// runHelp prints the whole help, or the verb named after help's own.
func runHelp(c *Call) int {
	if len(c.Args()) == 0 {
		Help(c.Name, c.Stdout)
		return 0
	}
	v, ok := lookup(c.Args()[0])
	if !ok {
		return refuse(c.Name, c.Args()[0], c.Stderr)
	}
	verbHelp(c.Name, v, newFlags(c.Name, v, c.Stderr), c.Stdout)
	return 0
}
