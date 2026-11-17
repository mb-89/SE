package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
)

// The se the agent tests run, built once for the package: its start replaces
// the process, so it runs as a binary.
var (
	builtOnce sync.Once
	builtSE   string
	builtErr  error
	builtDir  string
)

func TestMain(m *testing.M) {
	code := m.Run()
	if builtDir != "" {
		os.RemoveAll(builtDir)
	}
	os.Exit(code)
}

func seBinary(t *testing.T) string {
	t.Helper()
	builtOnce.Do(func() {
		if builtDir, builtErr = os.MkdirTemp("", "se-agent-test"); builtErr != nil {
			return
		}
		builtSE = filepath.Join(builtDir, "se")
		var out []byte
		if out, builtErr = exec.Command("go", "build", "-o", builtSE, ".").CombinedOutput(); builtErr != nil {
			builtErr = &buildError{builtErr, string(out)}
		}
	})
	if builtErr != nil {
		t.Fatal(builtErr)
	}
	return builtSE
}

type buildError struct {
	err error
	out string
}

func (e *buildError) Error() string { return "go build of cmd/se: " + e.err.Error() + "\n" + e.out }

// fakeHost is a claude that keeps its marketplaces and plugins in files of
// state and records each call as `<working directory>|<arguments>`; and a
// copilot that records its calls alike.
const fakeClaude = `#!/bin/bash
state="$FAKE_STATE"
printf '%s|%s\n' "$PWD" "$*" >>"$state/calls"
case "$*" in
"plugin marketplace list --json") cat "$state/markets.json" 2>/dev/null || echo '[]' ;;
"plugin list --json") cat "$state/plugins.json" 2>/dev/null || echo '[]' ;;
"plugin install se --marketplace "*)
	all="$*"; home="${all#plugin install se --marketplace }"
	printf '[{"name":"se","source":"directory","path":"%s"}]' "$home" >"$state/markets.json"
	printf '[{"id":"se@se","enabled":true,"readFromFolder":"%s"}]' "$home" >"$state/plugins.json" ;;
"plugin install se@se" | "plugin enable se@se") printf '[{"id":"se@se","enabled":true}]' >"$state/plugins.json" ;;
*) echo "claude ran" ;;
esac
`

const fakeCopilot = `#!/bin/bash
printf '%s|%s\n' "$PWD" "$*" >>"$FAKE_STATE/calls"
echo "copilot ran"
`

type agentBox struct {
	t       *testing.T
	state   string
	home    string
	project string
	env     []string
}

func newAgentBox(t *testing.T) *agentBox {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake hosts are bash scripts; Windows would need another form")
	}
	bash, err := exec.LookPath("bash")
	if err != nil {
		t.Skip("no bash for the fake hosts")
	}
	b := &agentBox{t: t, state: t.TempDir(), home: t.TempDir(), project: t.TempDir()}
	bin := t.TempDir()
	for name, script := range map[string]string{"claude": fakeClaude, "copilot": fakeCopilot} {
		if err := os.WriteFile(filepath.Join(bin, name), []byte(strings.Replace(script, "/bin/bash", bash, 1)), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	b.makeSE(b.home)
	for _, kv := range os.Environ() {
		name, _, _ := strings.Cut(kv, "=")
		switch name {
		case "PATH", "CLAUDECODE", "CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS", "RUNME_ROOT", "FAKE_STATE":
			continue
		}
		b.env = append(b.env, kv)
	}
	b.env = append(b.env, "PATH="+bin+string(os.PathListSeparator)+os.Getenv("PATH"), "FAKE_STATE="+b.state)
	return b
}

// makeSE makes dir an SE to load.
func (b *agentBox) makeSE(dir string) {
	b.t.Helper()
	if err := os.MkdirAll(filepath.Join(dir, ".claude-plugin"), 0o755); err != nil {
		b.t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, marketplaceFile), []byte(`{"name":"se"}`), 0o644); err != nil {
		b.t.Fatal(err)
	}
}

func (b *agentBox) write(name, content string) {
	b.t.Helper()
	if err := os.WriteFile(filepath.Join(b.state, name), []byte(content), 0o644); err != nil {
		b.t.Fatal(err)
	}
}

// run runs se with args in the project, env added, and answers its stdout,
// stderr and exit code.
func (b *agentBox) run(env []string, args ...string) (string, string, int) {
	b.t.Helper()
	cmd := exec.Command(seBinary(b.t), args...)
	cmd.Dir, cmd.Env = b.project, append(append([]string(nil), b.env...), env...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		b.t.Fatal(err)
	}
	return stdout.String(), stderr.String(), code
}

// calls are the fake hosts' calls since the last, each `<dir>|<arguments>`.
func (b *agentBox) calls() []string {
	b.t.Helper()
	path := filepath.Join(b.state, "calls")
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil
	} else if err != nil {
		b.t.Fatal(err)
	}
	os.Remove(path)
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

func (b *agentBox) realProject() string {
	real, err := filepath.EvalSymlinks(b.project)
	if err != nil {
		b.t.Fatal(err)
	}
	return real
}

func countOf(calls []string, part string) int {
	n := 0
	for _, c := range calls {
		if strings.Contains(c, part) {
			n++
		}
	}
	return n
}

// A bare se with no terminal prints the help and starts nothing, as it does
// inside Claude Code and on a cloud box.
func TestABareSEWithoutATerminalPrintsTheHelp(t *testing.T) {
	b := newAgentBox(t)
	help, _, code := b.run(nil, "help")
	if code != 0 || !strings.Contains(help, "\nHosts and hooks call these:\n") {
		t.Fatalf("se help exits %d with:\n%s", code, help)
	}
	b.calls()
	for _, env := range [][]string{nil, {"CLAUDECODE=1"}, {"CLAUDE_CODE_REMOTE=true", "RUNME_ROOT=" + b.home}} {
		out, stderr, code := b.run(env)
		if code != 0 || out != help {
			t.Fatalf("a bare se with %v exits %d with stdout\n%s\nstderr %q, and wants the help with 0", env, code, out, stderr)
		}
		if calls := b.calls(); countOf(calls, "--agent") > 0 {
			t.Fatalf("a bare se with %v started a host: %v", env, calls)
		}
	}
}

// The checks of a bare run in their order, the first that holds winning: no
// terminal, then CLAUDECODE, then a cloud mark of the SE it would load, read
// from that SE's host table, and only then.
func TestTheBareRunsDecision(t *testing.T) {
	seRoot, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	if len(cloudMarks(seRoot)) == 0 {
		t.Fatal("SE's scripts/hosts.sh names no cloud mark")
	}
	env := func(kv ...string) func(string) (string, bool) {
		return func(name string) (string, bool) {
			for _, e := range kv {
				if n, v, _ := strings.Cut(e, "="); n == name {
					return v, true
				}
			}
			return "", false
		}
	}
	asked := 0
	home := func(h string) func() string { return func() string { asked++; return h } }
	cases := []struct {
		lookup   func(string) (string, bool)
		terminal bool
		home     string
		helps    bool
		asks     int
	}{
		{env(), false, seRoot, true, 0},
		{env("CLAUDECODE="), true, seRoot, true, 0},
		{env("CLAUDE_CODE_REMOTE=TRUE"), true, seRoot, true, 1},
		{env("GITHUB_ACTIONS=true"), true, seRoot, true, 1},
		{env("CLAUDE_CODE_REMOTE=false"), true, seRoot, false, 1},
		{env("CLAUDE_CODE_REMOTE=true"), true, "", false, 1},
		{env(), true, seRoot, false, 1},
	}
	for i, c := range cases {
		asked = 0
		if got := bareHelps(c.lookup, c.terminal, home(c.home)); got != c.helps || asked != c.asks {
			t.Fatalf("case %d: the bare run helps %v after %d home lookups, and wants %v after %d", i, got, asked, c.helps, c.asks)
		}
	}
	if null, err := os.Open(os.DevNull); err == nil {
		defer null.Close()
		if terminal(null) {
			t.Fatal("the null device reads as a terminal")
		}
	}
}

// The home comes from --home, then RUNME_ROOT, then the directory
// marketplace se; with none, or a --home that holds no SE, se agent names
// RUNME and exits 2.
func TestTheHomesOrder(t *testing.T) {
	b := newAgentBox(t)
	if _, stderr, code := b.run(nil, "agent"); code != 2 || !strings.Contains(stderr, "RUNME") {
		t.Fatalf("se agent with no home exits %d with %q, and wants RUNME named with 2", code, stderr)
	}
	if _, stderr, code := b.run(nil, "agent", "--home", b.project); code != 2 || !strings.Contains(stderr, "RUNME") || !strings.Contains(stderr, "--home") {
		t.Fatalf("se agent --home of no SE exits %d with %q, and wants RUNME and --home named with 2", code, stderr)
	}
	b.calls()
	other := t.TempDir()
	b.makeSE(other)
	b.write("markets.json", `[{"name":"se","source":"directory","path":"`+b.home+`"}]`)
	b.write("plugins.json", `[{"id":"se@se","enabled":true}]`)
	// RUNME_ROOT of another tool, no SE, is passed over for the marketplace.
	if _, stderr, code := b.run([]string{"RUNME_ROOT=" + b.project}, "agent"); code != 0 {
		t.Fatalf("se agent with another tool's RUNME_ROOT exits %d: %s", code, stderr)
	}
	if calls := b.calls(); countOf(calls, "plugin install") != 0 || countOf(calls, "--agent se:se") != 1 {
		t.Fatalf("se agent from the marketplace's home calls %v", calls)
	}
	// RUNME_ROOT with an SE comes before the marketplace: a home other than
	// its se's, so it is refused with its fix line.
	if _, stderr, code := b.run([]string{"RUNME_ROOT=" + other}, "agent"); code != 1 || !strings.Contains(stderr, "already reads the marketplace se from "+b.home) {
		t.Fatalf("se agent with RUNME_ROOT of another SE exits %d with %q", code, stderr)
	}
	// --home comes before RUNME_ROOT.
	if _, stderr, code := b.run([]string{"RUNME_ROOT=" + other}, "agent", "--home", b.home); code != 0 {
		t.Fatalf("se agent --home before RUNME_ROOT exits %d: %s", code, stderr)
	}
}

// With no marketplace se, se agent installs SE from the home once; a second
// run installs nothing. Claude Code starts in the caller's folder with the
// arguments after --.
func TestAgentInstallsOnceAndStartsClaudeInTheCallersFolder(t *testing.T) {
	b := newAgentBox(t)
	out, stderr, code := b.run(nil, "agent", "--home", b.home, "--", "--version", "x y")
	if code != 0 || out != "claude ran\n" {
		t.Fatalf("se agent exits %d with stdout %q, stderr %q", code, out, stderr)
	}
	calls := b.calls()
	if countOf(calls, "|plugin install se --marketplace "+b.home) != 1 {
		t.Fatalf("se agent with no marketplace se calls %v, and wants one install from %s", calls, b.home)
	}
	if last := calls[len(calls)-1]; last != b.realProject()+"|--agent se:se --version x y" {
		t.Fatalf("se agent starts %q, and wants claude --agent se:se --version x y in %s", last, b.realProject())
	}
	if _, stderr, code := b.run(nil, "agent", "--home", b.home); code != 0 {
		t.Fatalf("a second se agent exits %d: %s", code, stderr)
	}
	if calls := b.calls(); countOf(calls, "plugin install") != 0 || countOf(calls, "plugin enable") != 0 {
		t.Fatalf("a second se agent calls %v, and wants no install", calls)
	}
}

// A marketplace se from another source, or a plugin se other than se@se:
// its one fix line, exit 1, and no install; a disabled se@se is enabled.
func TestAgentRefusesAnotherSEAndEnablesADisabledOne(t *testing.T) {
	b := newAgentBox(t)
	b.write("markets.json", `[{"name":"se","source":"github","repo":"alice/se"}]`)
	_, stderr, code := b.run(nil, "agent", "--home", b.home)
	if code != 1 || !strings.Contains(stderr, "se: Claude Code already reads the marketplace se from alice/se; to load SE from "+b.home+
		", run: claude plugin marketplace remove se (it also uninstalls se@se), then run RUNME again") {
		t.Fatalf("se agent beside another marketplace se exits %d with %q", code, stderr)
	}
	if calls := b.calls(); countOf(calls, "plugin install") != 0 || countOf(calls, "--agent") != 0 {
		t.Fatalf("se agent beside another marketplace se calls %v", calls)
	}
	b.write("markets.json", `[{"name":"se","source":"directory","path":"`+b.home+`"}]`)
	b.write("plugins.json", `[{"id":"se@skills-dir","enabled":true,"installPath":"/opt/claude/skills/se"},{"id":"se@se","enabled":true}]`)
	_, stderr, code = b.run(nil, "agent", "--home", b.home)
	if code != 1 || !strings.Contains(stderr, "se: Claude Code also loads a plugin se from /opt/claude/skills/se; remove it, then run RUNME again") {
		t.Fatalf("se agent beside another plugin se exits %d with %q", code, stderr)
	}
	if calls := b.calls(); countOf(calls, "plugin install") != 0 || countOf(calls, "--agent") != 0 {
		t.Fatalf("se agent beside another plugin se calls %v", calls)
	}
	b.write("plugins.json", `[{"id":"se@se","enabled":false}]`)
	if _, stderr, code := b.run(nil, "agent", "--home", b.home); code != 0 {
		t.Fatalf("se agent with a disabled se@se exits %d: %s", code, stderr)
	}
	if calls := b.calls(); countOf(calls, "|plugin enable se@se") != 1 || countOf(calls, "plugin install") != 0 {
		t.Fatalf("se agent with a disabled se@se calls %v, and wants one enable", calls)
	}
}

// --host copilot starts Copilot CLI in the caller's folder with SE loaded
// from the home for that run, and the arguments after --.
func TestAgentStartsCopilotWithThePluginDir(t *testing.T) {
	b := newAgentBox(t)
	out, stderr, code := b.run(nil, "agent", "--host", "copilot", "--home", b.home, "--", "-p", "status")
	if code != 0 || out != "copilot ran\n" {
		t.Fatalf("se agent --host copilot exits %d with stdout %q, stderr %q", code, out, stderr)
	}
	calls := b.calls()
	if want := b.realProject() + "|--plugin-dir=" + b.home + " --agent se -p status"; len(calls) != 1 || calls[0] != want {
		t.Fatalf("se agent --host copilot calls %v, and wants %q", calls, want)
	}
}
