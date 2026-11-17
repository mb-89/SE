package cli_test

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"

	"kern/cli"
)

func runCLI(args ...string) (string, string, int) {
	var stdout, stderr bytes.Buffer
	code := cli.Run("kern", args, &stdout, &stderr)
	return stdout.String(), stderr.String(), code
}

// help, --help and -h print one help on stdout with exit 0, and it names
// every verb of the table with its arguments, under the heading of those
// hosts and hooks call where they do.
func TestHelpListsEveryVerbOnStdout(t *testing.T) {
	help, stderr, code := runCLI("help")
	if code != 0 || stderr != "" {
		t.Fatalf("kern help exits %d with stderr %q, and wants 0 with none", code, stderr)
	}
	for _, flag := range []string{"--help", "-h"} {
		if out, _, code := runCLI(flag); out != help || code != 0 {
			t.Fatalf("kern %s exits %d with\n%s\nand wants the help of kern help with 0:\n%s", flag, code, out, help)
		}
	}
	if !strings.Contains(help, "usage: kern [<verb>] [<options>]\n") {
		t.Fatalf("the help names no usage line:\n%s", help)
	}
	person, hosts, found := strings.Cut(help, "\nHosts and hooks call these:\n")
	if !found {
		t.Fatalf("the help has no heading for the verbs hosts and hooks call:\n%s", help)
	}
	for _, v := range cli.Verbs() {
		section := person
		if v.Hosts {
			section = "\n" + hosts
		}
		if !strings.Contains(section, "\n  "+strings.TrimSpace(v.Name+" "+v.Args)+" ") {
			t.Fatalf("the help names no line for %q in its section:\n%s", v.Name, help)
		}
	}
	if !strings.Contains(help, "\nExit codes:\n") || !strings.Contains(help, "--unanswered N") {
		t.Fatalf("the help names no exit codes, hook's among them:\n%s", help)
	}
}

// Each verb's -h and --help print its usage and flags on stdout with exit 0,
// hook's among them, which fails open on every other flag error.
func TestEveryVerbsHelpExitsZero(t *testing.T) {
	for _, v := range cli.Verbs() {
		for _, flag := range []string{"-h", "--help"} {
			out, stderr, code := runCLI(v.Name, flag)
			if code != 0 || stderr != "" || !strings.HasPrefix(out, "usage: kern "+v.Name) {
				t.Fatalf("kern %s %s exits %d with stdout %q and stderr %q, and wants its usage on stdout with 0", v.Name, flag, code, out, stderr)
			}
		}
	}
	if out, _, _ := runCLI("status", "-h"); !strings.Contains(out, "-json") {
		t.Fatalf("kern status -h names no -json:\n%s", out)
	}
	if out, _, code := runCLI("help", "status"); code != 0 || !strings.Contains(out, "-json") {
		t.Fatalf("kern help status exits %d with %q, and wants status's options with 0", code, out)
	}
}

// An unknown verb, and a bare run where the application sets none, name the
// usage line and the help on stderr with exit 2.
func TestAnUnknownVerbNamesTheHelp(t *testing.T) {
	out, stderr, code := runCLI("begin")
	if code != 2 || out != "" || !strings.Contains(stderr, `kern: no command "begin"`) ||
		!strings.Contains(stderr, "kern help lists every verb") {
		t.Fatalf("kern begin exits %d with stdout %q and stderr %q", code, out, stderr)
	}
	if cli.Bare.Run != nil {
		t.Skip("the bare kern sets no bare run")
	}
	out, stderr, code = runCLI()
	if code != 2 || out != "" || !strings.HasPrefix(stderr, "usage: kern ") || !strings.Contains(stderr, "kern help lists every verb") {
		t.Fatalf("a bare kern exits %d with stdout %q and stderr %q", code, out, stderr)
	}
}

// Add refuses a name the table holds, naming both.
func TestAddRefusesANameKernHas(t *testing.T) {
	defer func() {
		said, _ := recover().(string)
		if !strings.Contains(said, `"start"`) || !strings.Contains(said, "mine") {
			t.Fatalf("Add of a second start panics with %q, and wants both named", said)
		}
	}()
	cli.Add(cli.Verb{Name: "start", Doc: "mine", Run: func(*cli.Call) int { return 0 }})
}

// kern/README.md's table in "The host" names exactly the table's verbs.
func TestTheReadmesHostTableNamesTheVerbs(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "README.md"))
	if err != nil {
		t.Fatal(err)
	}
	// Each line read without a trailing \r: the Windows leg checks the README out with CRLF.
	text := strings.ReplaceAll(string(data), "\r\n", "\n")
	_, section, _ := strings.Cut(text, "\n## The host\n")
	section, _, _ = strings.Cut(section, "\n## ")
	row := regexp.MustCompile("^\\| `kern ([a-z]+)")
	named := map[string]bool{}
	for _, line := range strings.Split(section, "\n") {
		if m := row.FindStringSubmatch(line); m != nil {
			named[m[1]] = true
		}
	}
	var got, want []string
	for name := range named {
		got = append(got, name)
	}
	for _, v := range cli.Verbs() {
		want = append(want, v.Name)
	}
	sort.Strings(got)
	sort.Strings(want)
	if strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("kern/README.md's host table names %v, and the verb table holds %v", got, want)
	}
}
