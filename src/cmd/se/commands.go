package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mb-89/SE/src/internal/daemon"
)

// Command is one word se answers. A command is one file that calls register
// in its init; the help and the session's /se are made from what registered.
type Command struct {
	// Name is the word that runs it: se <name>, or /se <name> in a session.
	// A name of two words, "issue next", is a sub-word of its first: the first
	// word alone then lists its sub-words.
	Name string
	// Usage is the command line after se, the name first: "serve [--idle D]".
	Usage string
	// Group is the heading it stands under in the help: "Session", "Issues".
	Group string
	// Summary is the help's one short line about it, no flags.
	Summary string
	// Details is what se help <name> says beyond the usage and the flags.
	Details string
	// Session offers it inside a Claude session as /se <name>.
	Session bool
	// Installed keeps it in the installed se when the session works in an SE
	// checkout; every other /se word goes to the se built from that checkout.
	Installed bool
	// Button offers it as a button in /se ui, pressed as /se <name> is typed.
	// Only a session command that takes no typed words is one.
	Button bool
	// Run does it and answers what to show, and in a session what the plugin applies.
	Run func(c *Call) (Reply, error)
}

// Reply is what a command answers. On a terminal se prints Text; in a session
// (--session) it prints the whole Reply as JSON for the plugin to apply.
type Reply struct {
	// Text is what to show.
	Text string `json:"text"`
	// Active, when set, switches forwarding on or off for the calling session.
	Active *bool `json:"active,omitempty"`
	// Endpoint, when set, is where the workspace's daemon now answers.
	Endpoint *Endpoint `json:"endpoint,omitempty"`
	// Reload asks the plugin to reload the session's plugins.
	Reload bool `json:"reload,omitempty"`
	// Panel, when set, asks the plugin to open /se ui with these buttons.
	Panel *Panel `json:"panel,omitempty"`
	// Help, when set, is the help Text says, as data the plugin draws.
	Help *Help `json:"help,omitempty"`
}

// Panel is what /se ui draws beside its on/off toggle.
type Panel struct {
	// Buttons are the names of the commands offered as buttons, in order.
	Buttons []string `json:"buttons"`
}

// Endpoint is the part of daemon.json the plugin posts with.
type Endpoint struct {
	Address string `json:"address"`
	Token   string `json:"token"`
}

func endpointOf(ep daemon.Endpoint) *Endpoint {
	return &Endpoint{Address: ep.Address, Token: ep.Token}
}

func switched(on bool) *bool { return &on }

// Call is one run of a command.
type Call struct {
	// Args are the words after the command's name.
	Args []string
	// Workspace is the folder the daemon serves, made absolute by Parse.
	Workspace string
	// Session is set when a Claude session called through /se.
	Session bool
	// Color is set when the help may colour what it prints.
	Color bool
	// flags is the flag set Flags made, which the command's help lists.
	flags *flag.FlagSet
}

var commands = map[string]Command{}

// register adds a command; a command file calls it from init.
func register(c Command) {
	if _, taken := commands[c.Name]; taken {
		panic("se: two commands named " + c.Name)
	}
	commands[c.Name] = c
}

// Flags is a flag set for the command that already takes --workspace.
func (c *Call) Flags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	fs.StringVar(&c.Workspace, "workspace", c.Workspace, "the workspace `DIR` the daemon serves (default: here)")
	c.flags = fs
	return fs
}

// Parse reads the command's flags; a command takes no words beyond them.
func (c *Call) Parse(fs *flag.FlagSet) error {
	if err := fs.Parse(c.Args); err != nil {
		return err
	}
	if fs.NArg() > 0 {
		return fmt.Errorf("%s takes no word %q", fs.Name(), fs.Arg(0))
	}
	root, err := filepath.Abs(c.Workspace)
	if err != nil {
		return err
	}
	c.Workspace = root
	return nil
}

// Paths names the workspace's runtime files.
func (c *Call) Paths() daemon.Paths { return daemon.Paths{Workspace: c.Workspace} }

// offered lists the commands a terminal (session false) or a session can run, by name.
func offered(session bool) []Command {
	var out []Command
	for _, c := range commands {
		if c.Session || !session {
			out = append(out, c)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

// subWords lists the second words of the commands under first that a terminal
// (session false) or a session can run.
func subWords(first string, session bool) []string {
	var out []string
	for _, c := range offered(session) {
		if rest, ok := strings.CutPrefix(c.Name, first+" "); ok && first != "" {
			out = append(out, rest)
		}
	}
	return out
}

func prog(session bool) string {
	if session {
		return "/se"
	}
	return "se"
}

// run is se: it reads --session and --workspace, then the command's name, and
// runs that command. It answers the exit code.
func run(args []string, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet("se", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	session := fs.Bool("session", false, "called by the plugin from a session: answer JSON")
	workspace := fs.String("workspace", ".", "the workspace the daemon serves")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(stderr, "se: %v\n%s\n", err, help(false, colors(stderr)))
		return 2
	}
	// The help is coloured on a terminal alone, never in a session's answer.
	color, errColor := !*session && colors(stdout), !*session && colors(stderr)
	call := &Call{Workspace: *workspace, Session: *session, Color: color}
	name := ""
	if fs.NArg() > 0 {
		name, call.Args = fs.Arg(0), fs.Args()[1:]
	}
	if len(call.Args) > 0 {
		if _, sub := commands[name+" "+call.Args[0]]; sub {
			name, call.Args = name+" "+call.Args[0], call.Args[1:]
		}
	}
	cmd, ok := commands[name]
	if *session && (!ok || !cmd.Installed) {
		if code, handed := handsOver(*workspace, args, stdout, stderr); handed {
			return code
		}
	}
	if ok && *session && !cmd.Session {
		ok = false
	}
	var reply Reply
	var err error
	switch {
	case ok:
		reply, err = cmd.Run(call)
		if errors.Is(err, flag.ErrHelp) {
			reply, err = helpReply(commandHelpOf(cmd, call.flags, *session), *session, color), nil
		}
	case name == "":
		reply = helpReply(overview(*session), *session, errColor)
		if !*session {
			fmt.Fprintln(stderr, reply.Text)
			return 2
		}
	case len(subWords(name, *session)) > 0:
		reply = Reply{Text: fmt.Sprintf("%s %s takes a word: %s.", prog(*session), name, strings.Join(subWords(name, *session), ", "))}
		if !*session {
			fmt.Fprintln(stderr, reply.Text)
			return 2
		}
	default:
		reply = Reply{Text: unknown(name, *session, errColor)}
		if !*session {
			fmt.Fprintln(stderr, reply.Text)
			return 2
		}
	}
	if *session {
		code := 0
		if err != nil {
			reply, code = Reply{Text: fmt.Sprintf("se %s: %v", name, err)}, 1
		}
		if err := json.NewEncoder(stdout).Encode(reply); err != nil {
			return 1
		}
		return code
	}
	if err != nil {
		fmt.Fprintln(stderr, "se:", err)
		return 1
	}
	if reply.Text != "" {
		fmt.Fprintln(stdout, reply.Text)
	}
	return 0
}

// executable is this se, the installed one when it runs from the plugin.
var executable = os.Executable
