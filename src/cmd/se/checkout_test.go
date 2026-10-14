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

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/io/proc"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/gitenv"
	"github.com/mb-89/SE/src/internal/update"
)

// repoRoot is the SE checkout these tests run in.
func repoRoot(t *testing.T) string {
	t.Helper()
	root, err := filepath.Abs("../../..")
	if err != nil || !update.IsCheckout(disk.Real(), root) {
		t.Fatalf("the tests do not run in an SE checkout: %s %v", root, err)
	}
	return root
}

func TestMain(m *testing.M) {
	// git's repository variables point it elsewhere under a pre-push hook.
	for _, v := range gitenv.Vars {
		_ = os.Unsetenv(v) // fails only on a name with "=" or NUL, which Vars hold none of
	}
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

// installed builds an se from this checkout to stand in for the installed
// se, since the test binary cannot serve as a daemon. A machine runs as it
// through runningAs.
func installed(t *testing.T) string {
	t.Helper()
	installedOnce.Do(func() {
		dir, err := os.MkdirTemp("", "se-installed-")
		if err != nil {
			installedErr = err
			return
		}
		installedSE = filepath.Join(dir, filepath.Base(daemon.Paths{}.Bin()))
		installedErr = update.Build(disk.Real(), proc.Real(), repoRoot(t), installedSE)
	})
	if installedErr != nil {
		t.Fatal(installedErr)
	}
	w := worldOf(t)
	w.Proc = runningAs{w.Proc, installedSE}
	return installedSE
}

// runningAs is a machine whose running program, its Self, is self.
type runningAs struct {
	proc.Procs
	self string
}

func (m runningAs) Self() (string, error) { return m.self, nil }

// scratch copies this checkout's source into a fresh workspace.
func scratch(t *testing.T) string {
	t.Helper()
	root, dst := repoRoot(t), t.TempDir()
	for _, part := range []string{"src/cmd", "src/internal", "src/go.mod", "src/go.sum"} {
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
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
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
	got, ok := daemon.Healthy(daemon.Paths{Workspace: ws, Disk: disk.Real()}, sehttp.Real())
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
	t.Parallel()
	for name, c := range commands {
		want := name == "on" || name == "restart" || name == "update"
		if c.Installed != want {
			t.Errorf("%s: installed %v, want %v", name, c.Installed, want)
		}
	}
}

func TestAnyOtherWorkspaceRunsTheInstalledSe(t *testing.T) {
	t.Parallel()
	se := installed(t)
	ws := t.TempDir()
	write(t, filepath.Join(ws, "src", "go.mod"), "module example.com/other\n")
	m, w := proc.NewFake(), worldOf(t)
	m.RunAs(se)
	w.Proc = m
	exe, note, err := daemonExe(w, daemon.Paths{Workspace: ws, Disk: disk.Real()})
	if err != nil || exe != se || note != "" || len(m.Ran()) != 0 {
		t.Fatalf("exe %q, note %q, err %v, ran %q", exe, note, err, m.Lines())
	}
	if _, err := os.Stat(daemon.Paths{Workspace: ws, Disk: disk.Real()}.Bin()); err == nil {
		t.Fatal("se was built in a workspace that is no SE checkout")
	}
}

func TestOnlySessionWordsGoToTheCheckoutsSe(t *testing.T) {
	t.Parallel()
	if runtime.GOOS == "windows" {
		t.Skip("the stand-in se is a shell script")
	}
	// The stand-in se runs on the real machine, where a test running beside
	// this one can hold it busy a moment; handsOver waits that out on the
	// real clock.
	worldOf(t).Clock = clock.Real()
	ws := t.TempDir()
	write(t, filepath.Join(ws, "src", "go.mod"), "module "+update.Module+"\n")
	bin := daemon.Paths{Workspace: ws, Disk: disk.Real()}.Bin()
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
	setenv(t, handedOver, "1")
	if r := in(t, ws, "help"); r.Text != help(true, false) {
		t.Errorf("handed over: %q", r.Text)
	}
}

func TestABusyCheckoutSeIsTriedAgainOnTheWorldsClock(t *testing.T) {
	t.Parallel()
	d := onFake(t)
	ws, _ := filepath.Abs("/ws")
	put(t, d, filepath.Join(ws, "src", "go.mod"), "module "+update.Module+"\n")
	bin := daemon.Paths{Workspace: ws, Disk: d}.Bin()
	put(t, d, bin, "built")
	m, w := proc.NewFake(), worldOf(t)
	m.Install(bin, func(c proc.Cmd) int { return 7 })
	w.Proc = m
	clk := clock.NewFake(testedAt)
	w.Clock = clk

	// Busy a few times, as a fork beside it holds it open: the run comes through.
	m.Busy(bin, 3)
	if code, handed := handsOver(w, ws, []string{"status"}, nil, nil); !handed || code != 7 {
		t.Fatalf("busy 3 times: exit %d, handed %v", code, handed)
	}
	if len(m.Ran()) != 4 || clk.Now().Sub(testedAt) != 3*busyWait {
		t.Fatalf("ran %q, waited %v", m.Lines(), clk.Now().Sub(testedAt))
	}

	// Busy past every try: this se answers itself.
	m.Busy(bin, busyTries)
	if _, handed := handsOver(w, ws, []string{"status"}, nil, nil); handed {
		t.Fatal("handed over to an se that never ran")
	}
	if len(m.Ran()) != 4+busyTries {
		t.Fatalf("tried %d times, want %d", len(m.Ran())-4, busyTries)
	}
}

func TestRestartRunsTheCheckoutsOwnSource(t *testing.T) {
	t.Parallel()
	if testing.Short() {
		t.Skip("builds se twice")
	}
	se := installed(t)
	ws := scratch(t)
	// Real daemons start and stop here, on the real clock they wait by.
	worldOf(t).Clock = clock.Real()
	paths := daemon.Paths{Workspace: ws, Disk: disk.Real()}
	t.Cleanup(func() { _ = daemon.Stop(paths, 5*time.Second, clock.Real(), sehttp.Real()) })

	// The checkout changes a summary and adds a command.
	helpGo := filepath.Join(ws, "src", "cmd", "se", "help.go")
	src, err := os.ReadFile(helpGo)
	if err != nil {
		t.Fatal(err)
	}
	write(t, helpGo, strings.Replace(string(src), `"list the commands, or show one: help <command>"`, `"list the commands, as edited"`, 1))
	write(t, filepath.Join(ws, "src", "cmd", "se", "hello.go"), `package main

func init() {
	register(Command{Name: "hello", Usage: "hello", Summary: "say hello", Session: true, Class: batch,
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
	if err := daemon.Stop(paths, 5*time.Second, clock.Real(), sehttp.Real()); err != nil {
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
	t.Parallel()
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

func TestWithdrawRemovesABuildOrMovesItAway(t *testing.T) {
	t.Parallel()
	d := disk.NewFake()
	bin := daemon.Paths{Workspace: filepath.FromSlash("/ws"), Disk: d}.Bin()
	put(t, d, bin, "se")
	withdraw(d, bin)
	if there, _ := d.Exists(bin); there {
		t.Fatal("the build stands")
	}
	withdraw(d, bin) // nothing to withdraw is no failure
	if names, _ := d.List(filepath.Dir(bin)); len(names) != 0 {
		t.Fatalf("left %v", names)
	}
}

func TestOnlyACheckoutWithABuildHandsOver(t *testing.T) {
	t.Parallel()
	d, ws := onFake(t), filepath.FromSlash("/ws")
	worldOf(t).Proc = proc.NewFake()
	if _, handed := handsOver(worldOf(t), ws, []string{"status"}, nil, nil); handed {
		t.Fatal("a folder that is no checkout handed over")
	}
	put(t, d, filepath.Join(ws, "src", "go.mod"), "module "+update.Module+"\n")
	if _, handed := handsOver(worldOf(t), ws, []string{"status"}, nil, nil); handed {
		t.Fatal("a checkout with nothing built handed over")
	}
}
