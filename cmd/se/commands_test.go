package main

import (
	"bytes"
	"encoding/json"
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
		"on": true, "off": true, "status": true, "update": true, "help": true, "restart": true, "issue next": true, "issue new": true, "issue land": true, "issue resume": true,
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
	terminal, inSession := help(false), help(true)
	for name, c := range commands {
		if !strings.Contains(terminal, "se "+c.Usage) || !strings.Contains(terminal, c.Summary) {
			t.Errorf("the terminal help leaves out %s:\n%s", name, terminal)
		}
		if got := strings.Contains(inSession, "/se "+name); got != c.Session {
			t.Errorf("the session help lists %s: %v, want %v:\n%s", name, got, c.Session, inSession)
		}
	}
}

func TestHelpOnATerminal(t *testing.T) {
	code, out, _ := se(t, "help")
	if code != 0 || out != help(false)+"\n" {
		t.Fatalf("exit %d, %q", code, out)
	}
}

func TestABareSeShowsTheHelp(t *testing.T) {
	if code, _, errs := se(t); code != 2 || !strings.Contains(errs, help(false)) {
		t.Fatalf("terminal: exit %d, %q", code, errs)
	}
	if r := session(t); r.Text != help(true) || r.Active != nil || r.Endpoint != nil || r.Reload {
		t.Fatalf("session: %+v", r)
	}
	if r := session(t, "help"); r.Text != help(true) {
		t.Fatalf("session help: %+v", r)
	}
}

func TestAnUnknownWordShowsTheHelpAndNamesIt(t *testing.T) {
	r := session(t, "frob")
	if !strings.HasPrefix(r.Text, help(true)) || !strings.Contains(r.Text, `"frob"`) {
		t.Fatalf("%q", r.Text)
	}
	code, _, errs := se(t, "frob")
	if code != 2 || !strings.Contains(errs, help(false)) || !strings.Contains(errs, `"frob"`) {
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
