// Package contract is kern's contract suite: it builds the kern binary and
// holds it to what docs/go-core.md promises of the bus and the host, through
// the commands a hook or a person runs. It runs in CI on Linux and on
// Windows. The suite against both fake cores joins it with the Python SDK.
package contract

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/host"
	"github.com/nats-io/nats.go"
)

// kern is the binary under test, built once for the suite.
var kern string

func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "kern-contract-")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	name := "kern"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	kern = filepath.Join(dir, name)
	build := exec.Command("go", "build", "-o", kern, "github.com/mb-89/kern/cmd/kern")
	build.Stdout, build.Stderr = os.Stderr, os.Stderr
	if err := build.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "contract: go build of cmd/kern failed:", err)
		os.Exit(2)
	}
	code := m.Run()
	_ = os.RemoveAll(dir)
	os.Exit(code)
}

// wait is how long a case waits for a core to come up or go down.
const wait = "20s"

type said struct {
	out  string
	code int
}

// run runs kern with args in env, and answers what it printed and its exit code.
func run(t *testing.T, env []string, args ...string) said {
	t.Helper()
	cmd := exec.Command(kern, args...)
	cmd.Env = append(os.Environ(), env...)
	var out bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &out
	err := cmd.Run()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		t.Fatalf("kern %s: %v", strings.Join(args, " "), err)
	}
	return said{strings.TrimSpace(out.String()), code}
}

func want(t *testing.T, got said, code int, text string) {
	t.Helper()
	if got.code != code || !strings.Contains(got.out, text) {
		t.Fatalf("kern answers %q with exit code %d, and wants %q with %d", got.out, got.code, text, code)
	}
}

// checkout is a fresh checkout whose core the case stops, whatever happens:
// Windows keeps a folder a process runs in.
func checkout(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, ".git"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		got := run(t, nil, "stop", "--root", root)
		if got.code != 0 {
			t.Errorf("the case's stop answers %q", got.out)
		}
	})
	return root
}

func standing(t *testing.T, root string) host.Standing {
	t.Helper()
	s, err := host.ReadStanding(root)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// `kern start` returns at once: it returns while the core it spawned is held
// before its bus, `kern status` answers starting, and running once it stands.
func TestStartReturnsAtOnceAndStatusAnswers(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	release := filepath.Join(t.TempDir(), "go")
	hold := []string{"KERN_HOLD_START=" + release}

	want(t, run(t, nil, "status", "--root", root), 1, "kern: not running in "+root)
	want(t, run(t, hold, "start", "--root", root), 0, "kern: started in "+root)
	want(t, run(t, nil, "status", "--root", root), 0, "kern: starting in "+root)
	if err := os.WriteFile(release, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running in "+root)

	got := run(t, nil, "status", "--root", root, "--json")
	var health struct {
		State  string      `json:"state"`
		Health host.Health `json:"health"`
	}
	if err := json.Unmarshal([]byte(got.out), &health); err != nil || health.State != "running" || health.Health.Contract != host.Contract {
		t.Fatalf("kern status --json answers %q, and wants the running core's health", got.out)
	}
	if _, err := os.Stat(host.ClaimPath(root)); !os.IsNotExist(err) {
		t.Fatalf("the claim outlives the core's start: %v", err)
	}

	pid := standing(t, root).Pid
	want(t, run(t, nil, "stop", "--root", root), 0, fmt.Sprintf("kern: stopped pid %d", pid))
	want(t, run(t, nil, "status", "--root", root), 1, "kern: not running")
	want(t, run(t, nil, "stop", "--root", root), 0, "kern: not running")
}

// Callers racing a start spawn one core: one claims, the rest see its claim,
// and a start where a core runs does nothing.
func TestRacingStartsSpawnOneCore(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	release := filepath.Join(t.TempDir(), "go")
	hold := []string{"KERN_HOLD_START=" + release}
	const callers = 4
	answers := make([]said, callers)
	var wg sync.WaitGroup
	for i := range answers {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			answers[i] = run(t, hold, "start", "--root", root)
		}(i)
	}
	wg.Wait()
	started := 0
	for _, a := range answers {
		if a.code != 0 {
			t.Fatalf("a racing start answers %q with %d", a.out, a.code)
		}
		if strings.Contains(a.out, "kern: started") {
			started++
		}
	}
	if started != 1 {
		t.Fatalf("racing starts answer %v, and want one start that spawned the core", answers)
	}
	if err := os.WriteFile(release, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
	want(t, run(t, nil, "start", "--root", root), 0, "kern: running in "+root)
}

// A standing file whose pid runs nowhere reads as absent: status says no core
// runs, and a start spawns a new one.
func TestAStandingFileOfAnEndedCoreReadsAsAbsent(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	ended := exec.Command(kern)
	_ = ended.Run() // exits 2 at once: its usage
	dir := filepath.Join(root, host.Runtime)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	gone, _ := json.Marshal(host.Standing{Contract: host.Contract, Pid: ended.ProcessState.Pid(), Root: root, Bus: "nats://127.0.0.1:1", Port: 1})
	if err := os.WriteFile(host.StandingPath(root), gone, 0o600); err != nil {
		t.Fatal(err)
	}
	want(t, run(t, nil, "status", "--root", root), 1, "kern: not running")
	want(t, run(t, nil, "start", "--root", root), 0, "kern: started")
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
}

// A machine restarted with the checkout's files kept, as a cloud
// environment restored from its snapshot is, gives its processes the pids of
// the last boot: the standing file of that boot's core names a pid that runs
// and is no core, and a bus that is gone. Two starts at once there leave
// exactly one running core, which wrote the standing file anew.
func TestTwoStartsOverAnEarlierBootsStandingFileLeaveOneCore(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	// The live process the earlier boot's pid now names: a kern held before
	// its bus, for another checkout, so it is no core of this one.
	other := exec.Command(kern, "serve", "--root", t.TempDir())
	other.Env = append(os.Environ(), "KERN_HOLD_START="+filepath.Join(t.TempDir(), "never"))
	if err := other.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = other.Process.Kill(); _ = other.Wait() })
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := l.Addr().(*net.TCPAddr).Port
	_ = l.Close()
	if err := os.MkdirAll(filepath.Join(root, host.Runtime), 0o700); err != nil {
		t.Fatal(err)
	}
	earlier, _ := json.Marshal(host.Standing{Contract: host.Contract, Pid: other.Process.Pid, Root: root, Bus: fmt.Sprintf("nats://127.0.0.1:%d", port), Port: port})
	if err := os.WriteFile(host.StandingPath(root), earlier, 0o600); err != nil {
		t.Fatal(err)
	}
	want(t, run(t, nil, "status", "--root", root), 1, "kern: not running")
	starts := make([]said, 2)
	var wg sync.WaitGroup
	for i := range starts {
		wg.Add(1)
		go func() {
			defer wg.Done()
			starts[i] = run(t, nil, "start", "--root", root)
		}()
	}
	wg.Wait()
	spawned := 0
	for _, s := range starts {
		if s.code != 0 {
			t.Fatalf("a start answers %q with exit code %d", s.out, s.code)
		}
		if strings.Contains(s.out, "kern: started") {
			spawned++
		}
	}
	if spawned != 1 {
		t.Fatalf("the two starts answer %q and %q, and want exactly one to start the core", starts[0].out, starts[1].out)
	}
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
	s := standing(t, root)
	if s.Pid == other.Process.Pid {
		t.Fatalf("the standing file still names the earlier boot's pid %d", s.Pid)
	}
	log, err := os.ReadFile(host.LogPath(root))
	if err != nil {
		t.Fatal(err)
	}
	if n := strings.Count(string(log), "kern: serving"); n != 1 || strings.Contains(string(log), "already runs") {
		t.Fatalf("the core's log says %q, and wants one core serving and none refused", log)
	}
}

// The standing file names the bus and a user for the core and for clients;
// a client from it asks the health, and the bus refuses it a commit.
func TestTheStandingFileLetsAClientAttach(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	want(t, run(t, nil, "start", "--root", root), 0, "kern: started")
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
	s := standing(t, root)
	if !strings.HasPrefix(s.Bus, "nats://127.0.0.1:") || s.Users[bus.Core] == "" || s.Users[bus.Client] == "" {
		t.Fatalf("the standing file says %+v, and wants a loopback bus with the core's and the client's users", s)
	}
	if runtime.GOOS != "windows" {
		st, err := os.Stat(host.StandingPath(root))
		if err != nil || st.Mode().Perm() != 0o600 {
			t.Fatalf("the standing file's mode is %v, %v, and wants 0600: it holds the passwords", st.Mode().Perm(), err)
		}
	}
	errs := make(chan error, 4)
	nc, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client], nats.ErrorHandler(func(_ *nats.Conn, _ *nats.Subscription, err error) { errs <- err }))
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	m, err := nc.Request(host.HealthSubject, nil, 5*time.Second)
	if err != nil || !strings.Contains(string(m.Data), fmt.Sprintf(`"pid":%d`, s.Pid)) {
		t.Fatalf("a client's health ask answers %v, %v", m, err)
	}
	_ = nc.Publish(bus.Commit+"anything", nil)
	_ = nc.Flush()
	select {
	case err := <-errs:
		if !strings.Contains(err.Error(), "Permissions Violation") {
			t.Fatalf("a client's commit answers %v, and wants a permissions violation", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the bus lets a client commit")
	}
}

// A hook event takes the session's lease, as the health shows.
func TestAHookTakesItsSessionsLease(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	want(t, run(t, nil, "start", "--root", root), 0, "kern: started")
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
	s := standing(t, root)
	nc, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client])
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	if m, err := nc.Request(bus.Hook+"SessionStart", []byte(`{"session_id":"s1"}`), 5*time.Second); err != nil || !strings.Contains(string(m.Data), `"pass"`) {
		t.Fatalf("hook.SessionStart answers %v, %v, and wants the effect pass", m, err)
	}
	want(t, run(t, nil, "status", "--root", root), 0, "1 session(s)")
}

// A wrong verb or flag is a usage error.
func TestUsage(t *testing.T) {
	t.Parallel()
	want(t, run(t, nil), 2, "usage: kern")
	want(t, run(t, nil, "begin"), 2, `kern: no command "begin"`)
	want(t, run(t, nil, "status", "--root", filepath.Join(t.TempDir(), "none")), 2, "is no folder")
}

// `kern hook <event>` posts the host's hook JSON from stdin and takes the
// session's lease; where no core answers it prints nothing and exits 0, as
// every failure does: a host reads a hook's exit code 2 as a block.
func TestAHookPostsItsEventAndFailsOpen(t *testing.T) {
	t.Parallel()
	hook := func(root, stdin string, args ...string) (string, int) {
		t.Helper()
		cmd := exec.Command(kern, append([]string{"hook"}, args...)...)
		cmd.Dir, cmd.Stdin = root, strings.NewReader(stdin)
		out, err := cmd.Output()
		if ee, ok := err.(*exec.ExitError); ok {
			return string(out), ee.ExitCode()
		} else if err != nil {
			t.Fatal(err)
		}
		return string(out), 0
	}
	root := checkout(t)
	for _, args := range [][]string{{"PreToolUse"}, {}, {"no.word"}, {"Stop", "--bogus"}} {
		if out, code := hook(root, `{"session_id":"s1"}`, args...); out != "" || code != 0 {
			t.Fatalf("kern hook %q with no core prints %q with exit code %d, and wants nothing with 0", args, out, code)
		}
	}
	want(t, run(t, nil, "start", "--root", root), 0, "kern: started")
	if out, code := hook(root, `{"session_id":"s1","hook_event_name":"SessionStart"}`, "SessionStart", "--root", root); out != "" || code != 0 {
		t.Fatalf("kern hook SessionStart prints %q with exit code %d, and wants nothing with 0", out, code)
	}
	want(t, run(t, nil, "status", "--root", root), 0, "1 session(s)")
	if out, code := hook(root, `{"session_id":"s1"}`, "SessionEnd"); out != "" || code != 0 {
		t.Fatalf("kern hook SessionEnd prints %q with exit code %d, and wants nothing with 0", out, code)
	}
	want(t, run(t, nil, "status", "--root", root), 0, "0 session(s)")
}

// With --unanswered N, `kern hook` exits N where no command answered the
// event: no core runs, or the core binds no command to it.
func TestAnUnansweredHookExitsWithTheCodeItIsGiven(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	hook := func(args ...string) said {
		t.Helper()
		cmd := exec.Command(kern, append([]string{"hook", "Stop", "--root", root}, args...)...)
		cmd.Stdin = strings.NewReader(`{"session_id":"s1"}`)
		out, err := cmd.Output()
		code := 0
		if ee, ok := err.(*exec.ExitError); ok {
			code = ee.ExitCode()
		} else if err != nil {
			t.Fatal(err)
		}
		return said{string(out), code}
	}
	if got := hook("--unanswered", "3"); got != (said{"", 3}) {
		t.Fatalf("kern hook --unanswered 3 with no core answers %+v, and wants nothing with 3", got)
	}
	want(t, run(t, nil, "start", "--root", root), 0, "kern: started")
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
	if got := hook("--unanswered", "3"); got != (said{"", 3}) {
		t.Fatalf("kern hook --unanswered 3 for an event no command answers prints %+v, and wants nothing with 3", got)
	}
	if got := hook(); got != (said{"", 0}) {
		t.Fatalf("kern hook without --unanswered prints %+v, and wants nothing with 0", got)
	}
}

// A core that ends at its start is not silent (SE's docs/go-core.md "The
// start budget"): its status names the cause, the first hook that carries
// context but SessionStart tells the session once, with the first lines the
// core said, and a core that stands again clears it. The case is the one a
// released binary met: a wiring that names a component it does not register.
func TestACoreThatEndsAtItsStartIsToldOnce(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	wiring := filepath.Join(root, "wiring.toml")
	if err := os.WriteFile(wiring, []byte("[instances.retro-due]\ncomponent = \"retro-due\"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	want(t, run(t, nil, "start", "--root", root), 0, "kern: started in "+root)
	got := run(t, nil, "status", "--root", root, "--wait", wait, "--json")
	var status struct {
		State string `json:"state"`
		Died  string `json:"died"`
	}
	if err := json.Unmarshal([]byte(got.out), &status); err != nil || status.State != "not running" ||
		!strings.Contains(status.Died, "instance retro-due: no component retro-due is registered") {
		t.Fatalf("kern status --json answers %q, and wants the cause the core said", got.out)
	}
	want(t, run(t, nil, "status", "--root", root), 1, "the core ended at its start; it said:\n")

	want(t, run(t, nil, "hook", "SessionStart", "--root", root), 0, "")
	if got := run(t, nil, "hook", "SessionStart", "--root", root); strings.Contains(got.out, "additionalContext") {
		t.Fatalf("SessionStart, whose output the start does not show, took the report: %q", got.out)
	}
	got = run(t, nil, "hook", "PostToolUse", "--root", root)
	var out struct {
		HookSpecificOutput struct{ AdditionalContext string } `json:"hookSpecificOutput"`
	}
	line := got.out[strings.LastIndex(got.out, "\n")+1:]
	if err := json.Unmarshal([]byte(line), &out); err != nil {
		t.Fatalf("the first PostToolUse prints %q, and wants the host's hook JSON", got.out)
	}
	context := out.HookSpecificOutput.AdditionalContext
	if !strings.HasPrefix(context, "kern: failed: the core ended at its start; it said:\n") ||
		!strings.Contains(context, "no component retro-due is registered") ||
		!strings.Contains(filepath.ToSlash(context), filepath.ToSlash(host.LogPath(root))+" holds all it said") {
		t.Fatalf("the report reads %q", context)
	}
	if got := run(t, nil, "hook", "PostToolUse", "--root", root); strings.Contains(got.out, "additionalContext") {
		t.Fatalf("the report is told twice: %q", got.out)
	}

	if err := os.WriteFile(host.DiedPath(root), []byte("an earlier core's cause\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(wiring); err != nil {
		t.Fatal(err)
	}
	want(t, run(t, nil, "start", "--root", root), 0, "kern: started in "+root)
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running in "+root)
	if _, err := os.Stat(host.DiedPath(root)); !os.IsNotExist(err) {
		t.Fatalf("a core that stands leaves the cause of the one before: %v", err)
	}
}

// A core that stood and ended without its end, killed outright, is told once
// by the next hook that carries context, with the last lines of its log.
func TestACoreKilledOutrightIsToldOnce(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	want(t, run(t, nil, "start", "--root", root), 0, "kern: started in "+root)
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running in "+root)
	p, err := os.FindProcess(standing(t, root).Pid)
	if err != nil {
		t.Fatal(err)
	}
	if err := p.Kill(); err != nil {
		t.Fatal(err)
	}
	end := time.Now().Add(20 * time.Second)
	for run(t, nil, "status", "--root", root).code != 1 {
		if time.Now().After(end) {
			t.Fatal("the killed core still answers")
		}
		time.Sleep(10 * time.Millisecond)
	}
	got := run(t, nil, "hook", "UserPromptSubmit", "--root", root)
	var out struct {
		HookSpecificOutput struct{ AdditionalContext string } `json:"hookSpecificOutput"`
	}
	line := got.out[strings.LastIndex(got.out, "\n")+1:]
	if err := json.Unmarshal([]byte(line), &out); err != nil {
		t.Fatalf("the first UserPromptSubmit prints %q, and wants the host's hook JSON", got.out)
	}
	context := filepath.ToSlash(out.HookSpecificOutput.AdditionalContext)
	if !strings.HasPrefix(context, "kern: failed: the core ended without its end; the last lines of "+filepath.ToSlash(host.LogPath(root))+":\n") ||
		!strings.Contains(context, "kern: serving "+filepath.ToSlash(root)) {
		t.Fatalf("the report reads %q", context)
	}
	if got := run(t, nil, "hook", "UserPromptSubmit", "--root", root); strings.Contains(got.out, "additionalContext") {
		t.Fatalf("the report is told twice: %q", got.out)
	}
}

// A machine restored from its snapshot keeps the checkout's files and starts
// a new boot: the first hook of the new boot tells nothing of the earlier
// boot's core, which ended with its boot, and the core's log carries one
// start line per boot, so a session tells its own lines from the earlier ones.
func TestARestoredBootTellsNoStaleDeadCore(t *testing.T) {
	t.Parallel()
	root := checkout(t)
	bootA := []string{host.BootEnv + "=boot-a"}
	bootB := []string{host.BootEnv + "=boot-b"}
	want(t, run(t, bootA, "start", "--root", root), 0, "kern: started in "+root)
	want(t, run(t, bootA, "status", "--root", root, "--wait", wait), 0, "kern: running in "+root)
	var s host.Standing
	data, err := os.ReadFile(host.StandingPath(root))
	if err != nil || json.Unmarshal(data, &s) != nil || s.Boot != "boot-a" {
		t.Fatalf("the standing file reads %q (%v), and wants boot-a", data, err)
	}
	// The boot ends under the core: its process is gone, its files stay.
	p, err := os.FindProcess(s.Pid)
	if err != nil {
		t.Fatal(err)
	}
	if err := p.Kill(); err != nil {
		t.Fatal(err)
	}
	end := time.Now().Add(20 * time.Second)
	for run(t, bootA, "status", "--root", root).code != 1 {
		if time.Now().After(end) {
			t.Fatal("the killed core still answers")
		}
		time.Sleep(10 * time.Millisecond)
	}
	if got := run(t, bootB, "hook", "UserPromptSubmit", "--root", root); strings.Contains(got.out, "additionalContext") {
		t.Fatalf("the restored boot's first hook tells the earlier boot's core: %q", got.out)
	}
	want(t, run(t, bootB, "start", "--root", root), 0, "kern: started in "+root)
	want(t, run(t, bootB, "status", "--root", root, "--wait", wait), 0, "kern: running in "+root)
	if got := run(t, bootB, "hook", "UserPromptSubmit", "--root", root); strings.Contains(got.out, "ended without its end") {
		t.Fatalf("the restored boot's core reports a dead core: %q", got.out)
	}
	want(t, run(t, bootB, "stop", "--root", root), 0, "kern: stopped")
	log, err := os.ReadFile(host.LogPath(root))
	if err != nil {
		t.Fatal(err)
	}
	var starts []string
	for _, line := range strings.Split(string(log), "\n") {
		if strings.HasPrefix(line, "kern: start ") {
			starts = append(starts, line)
		}
	}
	if len(starts) != 2 || !strings.Contains(starts[0], ", boot boot-a, pid ") || !strings.Contains(starts[1], ", boot boot-b, pid ") {
		t.Fatalf("the core's log has the start lines %q, and wants one of boot-a, then one of boot-b", starts)
	}
}
