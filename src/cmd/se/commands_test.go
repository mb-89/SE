// Internal test package: package main cannot be imported.
package main

import (
	"bytes"
	"encoding/json"
	"os"
	"regexp"
	"strings"
	"testing"
)

func se(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	var out, errs bytes.Buffer
	code := run(args, &out, &errs)
	return code, out.String(), errs.String()
}

func session(t *testing.T, args ...string) Reply {
	t.Helper()
	code, out, _ := se(t, append([]string{"--session", "--workspace", t.TempDir()}, args...)...)
	var r Reply
	if err := json.Unmarshal([]byte(out), &r); err != nil {
		t.Fatalf("%v answered %q (exit %d): %v", args, out, code, err)
	}
	return r
}

func TestEveryCommandSaysWhatItIs(t *testing.T) {
	for name, c := range commands {
		if c.Name != name || c.Summary == "" || c.Run == nil || !strings.HasPrefix(c.Usage, name) {
			t.Errorf("command %q is incomplete: %+v", name, c)
		}
	}
}

func TestTheSessionIsOfferedItsCommandsAlone(t *testing.T) {
	want := map[string]bool{
		"on": true, "off": true, "status": true, "update": true, "help": true, "restart": true, "issue next": true, "issue new": true, "issue land": true, "issue review": true, "ui": true, "fleet check": true, "fleet fix": true, "briefing": true,
		"serve": false, "start": false, "stop": false,
	}
	for name, offered := range want {
		c, ok := commands[name]
		if !ok || c.Session != offered {
			t.Errorf("%s: registered %v, offered in a session %v; want offered %v", name, ok, c.Session, offered)
		}
	}
}

func TestTheHelpIsMadeFromTheRegistry(t *testing.T) {
	terminal, inSession := help(false, false), help(true, false)
	for name, c := range commands {
		line := regexp.MustCompile(`(?m)^  ` + regexp.QuoteMeta(name) + ` +` + regexp.QuoteMeta(c.Summary) + `$`)
		if !line.MatchString(terminal) {
			t.Errorf("the terminal help leaves out %s:\n%s", name, terminal)
		}
		if got := line.MatchString(inSession); got != c.Session {
			t.Errorf("the session help lists %s: %v, want %v:\n%s", name, got, c.Session, inSession)
		}
	}
}

func TestTheHelpGroupsTheCommands(t *testing.T) {
	want := map[string][]string{
		"Session": {"help", "off", "on", "restart", "status", "ui", "update"},
		"Issues":  {"issue land", "issue new", "issue next", "issue resume", "issue review"},
		"Daemon":  {"serve", "start", "stop"},
		"Fleet":   {"briefing", "fleet check", "fleet fix", "fleet prune"},
		"Retro":   {"retro collect", "retro new", "retro report"},
	}
	terminal := help(false, false)
	for group, names := range want {
		block := regexp.MustCompile(`(?m)^` + group + `:\n((?:  .*\n?)+)`).FindStringSubmatch(terminal)
		if block == nil {
			t.Fatalf("no group %s:\n%s", group, terminal)
		}
		var got []string
		for _, line := range strings.Split(strings.TrimRight(block[1], "\n"), "\n") {
			got = append(got, strings.Join(strings.Fields(strings.Split(line, "  ")[1]), " "))
		}
		if strings.Join(got, ",") != strings.Join(names, ",") {
			t.Errorf("%s lists %q, want %q", group, got, names)
		}
	}
}

func TestACommandStandsUnderTheGroupItRegisters(t *testing.T) {
	register(Command{
		Name: "zz probe", Usage: "zz probe", Group: "Probes", Summary: "probe the help", Session: true,
		Run: func(c *Call) (Reply, error) { return Reply{}, nil },
	})
	t.Cleanup(func() { delete(commands, "zz probe") })
	for _, session := range []bool{false, true} {
		if h := help(session, false); !regexp.MustCompile(`Probes:\n  zz probe +probe the help\n`).MatchString(h) {
			t.Errorf("session %v:\n%s", session, h)
		}
	}
}

func TestNoOverviewLineIsLongerThan80(t *testing.T) {
	for _, session := range []bool{false, true} {
		for _, line := range strings.Split(help(session, false), "\n") {
			if len(line) > 80 {
				t.Errorf("%d characters: %q", len(line), line)
			}
		}
	}
}

func TestTheSessionHelpIsAFencedBlockAfterItsFirstLine(t *testing.T) {
	h := help(true, false)
	if !strings.HasPrefix(h, "/se <command> [flags]\n```\nFleet:") || !strings.HasSuffix(h, "\n```") {
		t.Fatalf("%q", h)
	}
	if strings.HasPrefix(help(false, false), "```") {
		t.Fatal("the terminal help is fenced")
	}
}

func TestAColouredHelpColoursHeadingsAndNamesAlone(t *testing.T) {
	plain, colored := help(false, false), help(false, true)
	if strings.Contains(plain, "\x1b[") || !strings.Contains(colored, "\x1b[1mSession:\x1b[0m") || !strings.Contains(colored, "\x1b[36mstatus\x1b[0m") {
		t.Fatalf("%q", colored)
	}
	if got := regexp.MustCompile("\x1b\\[[0-9]*m").ReplaceAllString(colored, ""); got != plain {
		t.Fatalf("the colours move the text:\n%s", got)
	}
}

func TestAPipeAndASessionGetNoColour(t *testing.T) {
	if _, out, _ := se(t, "help"); strings.Contains(out, "\x1b[") {
		t.Fatalf("%q", out)
	}
	if colors(os.Stdout) && os.Getenv("NO_COLOR") == "" {
		t.Skip("stdout is a terminal")
	}
	if r := session(t, "help"); strings.Contains(r.Text, "\x1b[") {
		t.Fatalf("%q", r.Text)
	}
}

func TestTheHelpOfACommand(t *testing.T) {
	code, out, _ := se(t, "help", "issue", "next")
	if code != 0 {
		t.Fatalf("exit %d, %q", code, out)
	}
	for _, want := range []string{
		"se issue next [--in ROOT]",
		"Name the next ready se issue",
		"Flags:\n",
		"\n  --in ROOT          look inside the tree of issue ROOT for its ready leaves\n",
		"\n  --take             claim the next ready issue",
		"\n  --json ",
		"\n  --repo OWNER/NAME ",
		"\n  --workspace DIR ",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("lacks %q:\n%s", want, out)
		}
	}
	for _, line := range strings.Split(out, "\n") {
		if len(line) > 80 {
			t.Errorf("%d characters: %q", len(line), line)
		}
	}
	if _, flagged, _ := se(t, "issue", "next", "--help"); flagged != out {
		t.Errorf("se issue next --help:\n%s\nwant:\n%s", flagged, out)
	}
	usage, rest, _ := strings.Cut(strings.TrimSuffix(strings.TrimPrefix(out, "se"), "\n"), "\n\n")
	if r := session(t, "help", "issue", "next"); r.Text != "/se"+usage+"\n```\n"+rest+"\n```" {
		t.Errorf("/se help issue next:\n%s", r.Text)
	}
}

func TestEveryCommandHasItsHelp(t *testing.T) {
	for name, c := range commands {
		code, out, _ := se(t, "help", name)
		if code != 0 || !strings.HasPrefix(out, "se "+strings.Fields(c.Usage)[0]) {
			t.Errorf("se help %s: exit %d, %q", name, code, out)
		}
	}
}

func TestHelpOfAnUnknownCommand(t *testing.T) {
	if code, _, errs := se(t, "help", "frob"); code != 1 || !strings.Contains(errs, `"frob"`) {
		t.Fatalf("exit %d, %q", code, errs)
	}
	if _, out, _ := se(t, "help", "issue"); !strings.Contains(out, "  issue next") || strings.Contains(out, "  status") {
		t.Fatalf("se help issue: %q", out)
	}
}

func TestHelpOnATerminal(t *testing.T) {
	code, out, _ := se(t, "help")
	if code != 0 || out != help(false, false)+"\n" {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestABareSeShowsTheHelp(t *testing.T) {
	if code, _, errs := se(t); code != 2 || !strings.Contains(errs, help(false, false)) {
		t.Fatalf("terminal: exit %d, %q", code, errs)
	}
	if r := session(t); r.Text != help(true, false) || r.Active != nil || r.Endpoint != nil || r.Reload {
		t.Fatalf("session: %+v", r)
	}
	if r := session(t, "help"); r.Text != help(true, false) {
		t.Fatalf("session help: %+v", r)
	}
}

func TestAnUnknownWordShowsTheHelpAndNamesIt(t *testing.T) {
	r := session(t, "frob")
	if !strings.HasPrefix(r.Text, help(true, false)) || !strings.Contains(r.Text, `"frob"`) {
		t.Fatalf("%q", r.Text)
	}
	code, _, errs := se(t, "frob")
	if code != 2 || !strings.Contains(errs, help(false, false)) || !strings.Contains(errs, `"frob"`) {
		t.Fatalf("exit %d, %q", code, errs)
	}
}

func TestATerminalCommandIsUnknownInASession(t *testing.T) {
	r := session(t, "stop")
	if !strings.Contains(r.Text, `no command "stop"`) {
		t.Fatalf("%q", r.Text)
	}
}

func TestOffSwitchesTheSessionOff(t *testing.T) {
	r := session(t, "off")
	if r.Active == nil || *r.Active || r.Text != "SE is off." {
		t.Fatalf("%+v", r)
	}
}

func TestStatusWithoutADaemon(t *testing.T) {
	r := session(t, "status")
	if !strings.HasPrefix(r.Text, "No SE daemon answers") {
		t.Fatalf("%q", r.Text)
	}
}

func TestACommandRefusesAStrayWord(t *testing.T) {
	code, out, _ := se(t, "--session", "off", "now")
	if code != 1 || !strings.Contains(out, `takes no word \"now\"`) {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestTheWorkspaceFlagFollowsTheCommandToo(t *testing.T) {
	dir := t.TempDir()
	if code, out, errs := se(t, "status", "--workspace", dir); code != 0 || !strings.Contains(out, dir) {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
}

func TestUiOffersTheButtonCommandsFromTheRegistry(t *testing.T) {
	r := session(t, "ui")
	if r.Panel == nil {
		t.Fatalf("ui opened no panel: %+v", r)
	}
	want := []string{"issue next", "restart", "status", "update"}
	if strings.Join(r.Panel.Buttons, ",") != strings.Join(want, ",") {
		t.Errorf("ui offers %q, want %q", r.Panel.Buttons, want)
	}
}

func TestOnlySessionCommandsWithoutTypedWordsAreButtons(t *testing.T) {
	for name, c := range commands {
		if !c.Button {
			continue
		}
		if !c.Session {
			t.Errorf("%s is a button but not offered in a session", name)
		}
		// Whatever follows the name in its usage is optional: inside [ ].
		depth, asks := 0, false
		for _, r := range strings.TrimPrefix(c.Usage, name) {
			switch {
			case r == '[':
				depth++
			case r == ']':
				depth--
			case depth == 0 && r != ' ':
				asks = true
			}
		}
		if asks {
			t.Errorf("%s is a button but its usage %q asks for a word", name, c.Usage)
		}
	}
}

func TestNoSessionHelpOpensAFenceOnItsFirstLine(t *testing.T) {
	for _, words := range [][]string{{"help"}, {"help", "issue"}, {"help", "issue", "next"}, {"issue", "next", "--help"}, {"frob"}} {
		r := session(t, words...)
		if first, _, _ := strings.Cut(r.Text, "\n"); strings.Contains(first, "```") {
			t.Errorf("/se %s opens a fence on its first line: %q", strings.Join(words, " "), first)
		}
	}
}

func TestTheSessionHelpCarriesItsData(t *testing.T) {
	r := session(t, "help")
	if r.Help == nil || r.Help.Usage != "/se <command> [flags]" || len(r.Help.Flags) != 0 {
		t.Fatalf("%+v", r.Help)
	}
	listed := map[string]string{}
	for _, g := range r.Help.Groups {
		for _, c := range g.Commands {
			listed[c.Name] = g.Name
			if c.Summary != commands[c.Name].Summary || c.Usage != "/se "+commands[c.Name].Usage {
				t.Errorf("%s: %+v", c.Name, c)
			}
		}
	}
	for name, c := range commands {
		if want := map[bool]string{true: c.Group}[c.Session]; listed[name] != want {
			t.Errorf("%s stands under %q, want %q", name, listed[name], want)
		}
	}
	one := session(t, "help", "issue", "next")
	if one.Help == nil || one.Help.Usage == "" || one.Help.About == "" || len(one.Help.Groups) != 0 {
		t.Fatalf("%+v", one.Help)
	}
	flags := map[string]bool{}
	for _, f := range one.Help.Flags {
		flags[f.Name] = f.Usage != ""
	}
	if !flags["--in ROOT"] || !flags["--take"] || !flags["--workspace DIR"] {
		t.Fatalf("%+v", one.Help.Flags)
	}
	if r := session(t, "status"); r.Help != nil {
		t.Fatalf("/se status carries help: %+v", r.Help)
	}
}
