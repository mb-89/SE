// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/gitenv"
	"github.com/mb-89/SE/src/internal/update"
)

// repoRoot is the SE checkout these tests run in.
func repoRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs("../../..")
	if err != nil || !update.IsCheckout(root) {
		t.Fatalf("the tests do not run in an SE checkout: %s %v", root, err)
	}
	return root
}

func TestMain(m *testing.M) {
	gitenv.Clear()
	code := m.Run()
	if installedSE != "" {
		os.RemoveAll(filepath.Dir(installedSE))
	}
	os.Exit(code)
}

var (
	installedOnce sync.Once
	installedSE   string
	installedErr  error
)

// installed stands an se built from this checkout in for the installed se,
// since the test binary cannot serve as a daemon.
func installed(t *testing.T) string {
	t.Helper()
	installedOnce.Do(func() {
		dir, err := os.MkdirTemp("", "se-installed-")
		if err != nil {
			installedErr = err
			return
		}
		installedSE = filepath.Join(dir, filepath.Base(daemon.Paths{}.Bin()))
		installedErr = update.Build(repoRoot(t), installedSE)
	})
	if installedErr != nil {
		t.Fatal(installedErr)
	}
	was := executable
	executable = func() (string, error) { return installedSE, nil }
	t.Cleanup(func() { executable = was })
	return installedSE
}

// scratch copies this checkout's source into a fresh workspace.
func scratch(t *testing.T) string {
	t.Helper()
	root, dst := repoRoot(t), t.TempDir()
	for _, part := range []string{"go.mod", "go.sum", "src/cmd", "src/internal"} {
		err := filepath.WalkDir(filepath.Join(root, part), func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			rel, _ := filepath.Rel(root, path)
			if d.IsDir() {
				return os.MkdirAll(filepath.Join(dst, rel), 0o755)
			}
			data, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			return os.WriteFile(filepath.Join(dst, rel), data, 0o644)
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	return dst
}

func write(t *testing.T, path, text string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
}

func in(t *testing.T, ws string, args ...string) Reply {
	t.Helper()
	code, out, errs := se(t, append([]string{"--session", "--workspace", ws}, args...)...)
	var r Reply
	if err := json.Unmarshal([]byte(out), &r); err != nil {
		t.Fatalf("%v answered %q %q (exit %d): %v", args, out, errs, code, err)
	}
	return r
}

// runs says which binary the daemon at ep runs, where the OS tells.
func runs(t *testing.T, ep *Endpoint, ws string) string {
	t.Helper()
	if runtime.GOOS != "linux" {
		return ""
	}
	got, ok := daemon.Healthy(daemon.Paths{Workspace: ws})
	if !ok || ep == nil || got.Address != ep.Address {
		t.Fatalf("no daemon answers at %+v (healthy %v at %s)", ep, ok, got.Address)
	}
	exe, err := os.Readlink(filepath.Join("/proc", strconv.Itoa(got.PID), "exe"))
	if err != nil {
		t.Fatal(err)
	}
	return exe
}

func TestTheLifecycleStaysWithTheInstalledSe(t *testing.T) {
	for name, c := range commands {
		want := name == "on" || name == "restart" || name == "update"
		if c.Installed != want {
			t.Errorf("%s: installed %v, want %v", name, c.Installed, want)
		}
	}
}

func TestAnyOtherWorkspaceRunsTheInstalledSe(t *testing.T) {
	se := installed(t)
	ws := t.TempDir()
	write(t, filepath.Join(ws, "go.mod"), "module example.com/other\n")
	exe, note, err := daemonExe(daemon.Paths{Workspace: ws})
	if err != nil || exe != se || note != "" {
		t.Fatalf("exe %q, note %q, err %v", exe, note, err)
	}
	if _, err := os.Stat(daemon.Paths{Workspace: ws}.Bin()); err == nil {
		t.Fatal("se was built in a workspace that is no SE checkout")
	}
}

func TestOnlySessionWordsGoToTheCheckoutsSe(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the stand-in se is a shell script")
	}
	ws := t.TempDir()
	write(t, filepath.Join(ws, "go.mod"), "module github.com/mb-89/SE\n")
	bin := daemon.Paths{Workspace: ws}.Bin()
	if err := os.MkdirAll(filepath.Dir(bin), 0o755); err != nil {
		t.Fatal(err)
	}
	write(t, bin, "#!/bin/sh\necho '{\"text\":\"the checkout answers\"}'\n")
	if err := os.Chmod(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, words := range [][]string{{}, {"help"}, {"status"}, {"frob"}} {
		if r := in(t, ws, words...); r.Text != "the checkout answers" {
			t.Errorf("/se %v: %q", words, r.Text)
		}
	}
	// A terminal se, the debugger's se serve among them, runs as it was built.
	if code, out, _ := se(t, "--workspace", ws, "help"); code != 0 || out != help(false, false)+"\n" {
		t.Errorf("terminal help: exit %d, %q", code, out)
	}
	// An se the installed one handed the words to answers them itself.
	t.Setenv(handedOver, "1")
	if r := in(t, ws, "help"); r.Text != help(true, false) {
		t.Errorf("handed over: %q", r.Text)
	}
}

func TestRestartRunsTheCheckoutsOwnSource(t *testing.T) {
	if testing.Short() {
		t.Skip("builds se twice")
	}
	se := installed(t)
	ws := scratch(t)
	paths := daemon.Paths{Workspace: ws}
	t.Cleanup(func() { _ = daemon.Stop(paths, 5*time.Second) })

	// The checkout changes a summary and adds a command.
	helpGo := filepath.Join(ws, "src", "cmd", "se", "help.go")
	src, err := os.ReadFile(helpGo)
	if err != nil {
		t.Fatal(err)
	}
	write(t, helpGo, strings.Replace(string(src), `"list the commands, or show one: help <command>"`, `"list the commands, as edited"`, 1))
	write(t, filepath.Join(ws, "src", "cmd", "se", "hello.go"), `package main

func init() {
	register(Command{Name: "hello", Usage: "hello", Summary: "say hello", Session: true,
		Run: func(c *Call) (Reply, error) { return Reply{Text: "hello from the checkout"}, nil }})
}
`)
	if r := in(t, ws, "help"); strings.Contains(r.Text, "as edited") {
		t.Fatalf("the edit shows before a restart: %q", r.Text)
	}

	r := in(t, ws, "restart")
	if r.Endpoint == nil || !strings.Contains(r.Text, "restarted") || !strings.Contains(r.Text, "built from this checkout") {
		t.Fatalf("restart: %+v", r)
	}
	if exe := runs(t, r.Endpoint, ws); exe != "" && exe != paths.Bin() {
		t.Fatalf("the daemon runs %s, want %s", exe, paths.Bin())
	}
	help := in(t, ws, "help").Text
	if !strings.Contains(help, "as edited") || !strings.Contains(help, "\n  hello ") {
		t.Fatalf("help after the restart:\n%s", help)
	}
	if got := in(t, ws, "hello").Text; got != "hello from the checkout" {
		t.Fatalf("/se hello: %q", got)
	}
	first := r.Endpoint.Address

	// A second restart starts a new daemon, and says where it answers.
	r = in(t, ws, "restart")
	if r.Endpoint == nil || r.Endpoint.Address == first {
		t.Fatalf("second restart: %+v (first at %s)", r, first)
	}

	// Source that does not build leaves the daemon to the installed se, and says why.
	write(t, filepath.Join(ws, "src", "cmd", "se", "broken.go"), "package main\n\nfunc broken() { undefinedThing() }\n")
	r = in(t, ws, "restart")
	if r.Endpoint == nil || !strings.Contains(r.Text, "does not build") || !strings.Contains(r.Text, "undefinedThing") {
		t.Fatalf("broken restart: %+v", r)
	}
	if exe := runs(t, r.Endpoint, ws); exe != "" && exe != se {
		t.Fatalf("the daemon runs %s, want the installed %s", exe, se)
	}
	if help := in(t, ws, "help").Text; strings.Contains(help, "as edited") || strings.Contains(help, "/se hello") {
		t.Fatalf("help still comes from the stale build:\n%s", help)
	}

	// Once it builds again, /se on starts the rebuilt se.
	os.Remove(filepath.Join(ws, "src", "cmd", "se", "broken.go"))
	if err := daemon.Stop(paths, 5*time.Second); err != nil {
		t.Fatal(err)
	}
	r = in(t, ws, "on")
	if r.Endpoint == nil || !strings.Contains(r.Text, "built from this checkout") {
		t.Fatalf("on: %+v", r)
	}
	if help := in(t, ws, "help").Text; !strings.Contains(help, "\n  hello ") {
		t.Fatalf("help after on:\n%s", help)
	}
}

// The debugger builds se serve from the source open in VS Code; serve is never
// handed to another se, so a breakpoint there is the code that runs.
func TestTheDebuggerServesTheSourceItDebugs(t *testing.T) {
	data, err := os.ReadFile(filepath.Join(repoRoot(t), ".vscode", "launch.json"))
	if err != nil {
		t.Fatal(err)
	}
	var launch struct {
		Configurations []struct {
			Name    string   `json:"name"`
			Program string   `json:"program"`
			Args    []string `json:"args"`
		} `json:"configurations"`
	}
	if err := json.Unmarshal(data, &launch); err != nil {
		t.Fatal(err)
	}
	if len(launch.Configurations) == 0 {
		t.Fatal("launch.json has no configuration")
	}
	for _, c := range launch.Configurations {
		if c.Program != "${workspaceFolder}/src/cmd/se" || len(c.Args) == 0 || c.Args[0] != "serve" {
			t.Errorf("%s: debugs %s %v, want se serve from ${workspaceFolder}/src/cmd/se", c.Name, c.Program, c.Args)
		}
	}
	if commands["serve"].Session {
		t.Error("serve is offered in a session, where it could be handed to the checkout's se")
	}
}
