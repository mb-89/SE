package host_test

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	gitdoor "github.com/mb-89/kern/git"
	"github.com/mb-89/kern/git/gitfake"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
	"github.com/nats-io/nats.go"
)

// wait is how long a case waits on an event that comes within milliseconds.
const wait = 10 * time.Second

// placedArg makes this test binary a placed component's process.
const placedArg = "kern-test-placed"

func TestMain(m *testing.M) {
	switch os.Args[len(os.Args)-1] {
	case placedArg:
		os.Exit(placed())
	case callerArg:
		os.Exit(caller())
	}
	// Every test reaches git through kern's git door, on its fake.
	gitdoor.Use(gitfake.New())
	os.Exit(m.Run())
}

// placed is the pump's process: it dials the bus as its own user, tries to
// commit as the gauge, and commits the level 7 once the bus has refused
// that, or -1 where it let it through; then it beats until the core ends it.
func placed() int {
	refused, closed := make(chan error, 4), make(chan struct{})
	nc, err := bus.Dial(os.Getenv(bus.EnvBus), os.Getenv(bus.EnvUser), os.Getenv(bus.EnvToken),
		nats.ErrorHandler(func(_ *nats.Conn, _ *nats.Subscription, err error) { refused <- err }),
		nats.ClosedHandler(func(*nats.Conn) { close(closed) }))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	me := bus.Subject(os.Getenv(bus.EnvUser))
	_ = nc.Publish(bus.Lease+me, nil)
	_ = nc.Publish(bus.Commit+"gauge", []byte(`{"writes":[{"port":"reading","value":99}]}`))
	_ = nc.Flush()
	level := -1
	select {
	case err := <-refused:
		if errors.Is(err, nats.ErrPermissionViolation) {
			level = 7
		}
	case <-time.After(wait):
	}
	if _, err := nc.Request(bus.Commit+me, []byte(fmt.Sprintf(`{"writes":[{"port":"level","value":%d}]}`, level)), wait); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	for {
		select {
		case <-closed:
			return 0
		case <-time.After(host.Beat):
			_ = nc.Publish(bus.Lease+me, nil)
		}
	}
}

// clock is a clock the case moves; its waits never fire, so the case runs each check itself.
type clock struct {
	mu  sync.Mutex
	now time.Time
}

func newClock() *clock { return &clock{now: time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC)} }

func (c *clock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}
func (c *clock) After(time.Duration) <-chan time.Time { return make(chan time.Time) }
func (c *clock) move(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.now = c.now.Add(d)
}

var pump = index.Declare("pump", "Pumps a level.", index.Output("level", 0, "The level pumped."))
var gauge = index.Declare("gauge", "Reads a gauge.", index.Output("reading", 0, "The gauge's reading."))

func served(t *testing.T, o host.Options) *host.Core {
	t.Helper()
	if o.Root == "" {
		o.Root = t.TempDir()
	}
	c, err := host.Serve(o)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		c.Stop("the case ends")
		<-c.Ended()
	})
	return c
}

// as dials the core's bus as one of its users, read from its standing file.
func as(t *testing.T, c *host.Core, user string) *nats.Conn {
	t.Helper()
	s, err := c.Standing()
	if err != nil {
		t.Fatal(err)
	}
	nc, err := bus.Dial(s.Bus, user, s.Users[user])
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(nc.Close)
	return nc
}

func ask(t *testing.T, nc *nats.Conn, subject string, body any, into any) {
	t.Helper()
	data, _ := json.Marshal(body)
	m, err := nc.Request(subject, data, wait)
	if err != nil {
		t.Fatalf("%s: %v", subject, err)
	}
	if err := json.Unmarshal(m.Data, into); err != nil {
		t.Fatalf("%s answers %s: %v", subject, m.Data, err)
	}
}

func ended(t *testing.T, c *host.Core, want string) {
	t.Helper()
	select {
	case <-c.Ended():
	case <-time.After(wait):
		t.Fatalf("the core runs on, and should end because %s", want)
	}
	if !strings.Contains(c.Reason(), want) {
		t.Fatalf("the core ends because %q, and wants %q", c.Reason(), want)
	}
	if _, err := c.Standing(); !errors.Is(err, host.ErrNotRunning) {
		t.Fatalf("the ended core's standing file reads %v, and wants it gone", err)
	}
}

func running(t *testing.T, c *host.Core) {
	t.Helper()
	select {
	case <-c.Ended():
		t.Fatalf("the core ended because %s, and should run on", c.Reason())
	default:
	}
}

// Lifetime: with no session's lease the core runs out its grace and ends.
func TestTheCoreEndsAGraceAfterTheLastSession(t *testing.T) {
	t.Parallel()
	clk := newClock()
	c := served(t, host.Options{Clock: clk})
	clk.move(host.Grace - time.Second)
	c.Check()
	running(t, c)
	clk.move(time.Second)
	c.Check()
	ended(t, c, "no session has held a lease for 1m0s")
}

// Each hook event renews its session's lease, SessionEnd returns it, and the
// last one out leaves the core its grace.
func TestASessionsLeaseHoldsTheCore(t *testing.T) {
	t.Parallel()
	clk := newClock()
	c := served(t, host.Options{Clock: clk})
	client := as(t, c, bus.Client)
	var effect host.HookAnswer
	ask(t, client, bus.Hook+"SessionStart", map[string]string{"session_id": "s1"}, &effect)
	if effect.Effect != "pass" {
		t.Fatalf("a hook's effect is %q, and wants pass", effect.Effect)
	}
	clk.move(5 * time.Minute)
	c.Check()
	running(t, c)
	var h host.Health
	ask(t, client, host.HealthSubject, nil, &h)
	if len(h.Sessions) != 1 || h.Sessions[0] != "s1" {
		t.Fatalf("the health names the sessions %q, and wants [s1]", h.Sessions)
	}
	ask(t, client, bus.Hook+host.SessionEnd, map[string]string{"session_id": "s1"}, &effect)
	clk.move(host.Grace - time.Second)
	c.Check()
	running(t, c)
	clk.move(time.Second)
	c.Check()
	ended(t, c, "no session has held a lease")
}

// A session that holds its lease and posts nothing for the idle span ends the core all the same.
func TestTheCoreEndsWhenIdle(t *testing.T) {
	t.Parallel()
	clk := newClock()
	c := served(t, host.Options{Clock: clk})
	var effect host.HookAnswer
	ask(t, as(t, c, bus.Client), bus.Hook+"SessionStart", map[string]string{"session_id": "s1"}, &effect)
	clk.move(host.Idle - time.Second)
	c.Check()
	running(t, c)
	clk.move(time.Second)
	c.Check()
	ended(t, c, "no event for 30m0s")
}

// A client stops the core on call.core.stop, and hears its pid first: the bus
// stays up until the client has the answer and hangs up, as kern stop does.
func TestAClientStopsTheCore(t *testing.T) {
	t.Parallel()
	c := served(t, host.Options{Clock: newClock()})
	nc := as(t, c, bus.Client)
	var said map[string]int
	ask(t, nc, host.StopSubject, nil, &said)
	nc.Close()
	if said["pid"] != os.Getpid() {
		t.Fatalf("the stop answers %v, and wants the core's pid %d", said, os.Getpid())
	}
	ended(t, c, "asked to stop")
}

// A client that stays on after the stop's answer delays the stop by HangUp at most.
func TestAStopEndsTheCoreThoughItsAskerStaysOn(t *testing.T) {
	t.Parallel()
	c := served(t, host.Options{Clock: newClock()})
	var said map[string]int
	asked := time.Now()
	ask(t, as(t, c, bus.Client), host.StopSubject, nil, &said)
	ended(t, c, "asked to stop")
	if took := time.Since(asked); took < host.HangUp || took > host.HangUp+wait {
		t.Fatalf("the core ends %v after the stop, and wants about %v", took, host.HangUp)
	}
}

// One core per checkout: a second one in the same root is refused.
func TestASecondCoreInOneCheckoutIsRefused(t *testing.T) {
	t.Parallel()
	c := served(t, host.Options{Clock: newClock()})
	s, _ := c.Standing()
	if _, err := host.Serve(host.Options{Root: s.Root, Clock: newClock()}); err == nil || !strings.Contains(err.Error(), "already runs") {
		t.Fatalf("a second core in one checkout starts with %v, and wants a refusal", err)
	}
}

// closedBus answers a bus URL on the loopback that nothing listens on.
func closedBus(t *testing.T) (string, int) {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := l.Addr().(*net.TCPAddr).Port
	_ = l.Close()
	return fmt.Sprintf("nats://127.0.0.1:%d", port), port
}

// earlierBoot writes the standing file a core of the machine's last boot
// left in the checkout: it names pid, which runs in this boot, and a bus
// that is gone.
func earlierBoot(t *testing.T, root string, pid int) {
	t.Helper()
	url, port := closedBus(t)
	data, _ := json.Marshal(host.Standing{Contract: host.Contract, Pid: pid, Root: root, Bus: url, Port: port})
	if err := os.MkdirAll(filepath.Join(root, host.Runtime), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(host.StandingPath(root), data, 0o600); err != nil {
		t.Fatal(err)
	}
}

// A standing file whose pid runs and whose bus accepts nothing names no
// core: the pid is another process's, as after a restart that kept the files.
// It reads as a core that ended without its end, told once.
func TestAStandingFileWhoseBusIsGoneReadsAsVanished(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	earlierBoot(t, root, os.Getpid())
	_, err := host.ReadStanding(root)
	if !errors.Is(err, host.ErrReused) || !errors.Is(err, host.ErrVanished) || !errors.Is(err, host.ErrNotRunning) {
		t.Fatalf("the standing file of an earlier boot reads as %v, and wants ErrReused, vanished and not running", err)
	}
	if _, ok := host.TakeVanished(root); !ok {
		t.Fatal("the standing file of an earlier boot is not taken as a core that ended without its end")
	}
	if _, ok := host.TakeVanished(root); ok {
		t.Fatal("the standing file of an earlier boot is told twice")
	}
}

// The core that serves meets the standing file of an earlier boot that
// names its own pid, and stands, since that file's bus is gone; the start
// that met it took the core for running and the checkout ran none.
func TestACoreServesOverAStandingFileNamingItsOwnPid(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	earlierBoot(t, root, os.Getpid())
	c, err := host.Serve(host.Options{Root: root, Clock: newClock()})
	if err != nil {
		t.Fatalf("a core over the standing file of an earlier boot naming its pid answers %v, and wants to serve", err)
	}
	t.Cleanup(func() { c.Stop("the case ends"); <-c.Ended() })
	s, err := c.Standing()
	if err != nil || s.Pid != os.Getpid() || s.Bus != c.Health().Bus {
		t.Fatalf("the standing file reads %+v, %v, and wants this core's bus %s", s, err, c.Health().Bus)
	}
}

// A container restored from its snapshot may keep its boot id and hand the
// last core's pid to another process, whose bus port something accepts on:
// the standing file's start mark tells that process from its core, and a
// core serves over the file. A dead pid of this boot and a foreign boot id
// let it serve too.
func TestACoreServesOverARecordThatNamesNoCore(t *testing.T) {
	t.Parallel()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	live := fmt.Sprintf("nats://%s", l.Addr())
	port := l.Addr().(*net.TCPAddr).Port
	skipWithoutMark(t)
	reused := host.Standing{Contract: host.Contract, Pid: os.Getpid(), Proc: "another-start", Boot: host.Boot(), Bus: live, Port: port}
	dead := host.Standing{Contract: host.Contract, Pid: endedPid(t), Boot: host.Boot(), Bus: live, Port: port}
	// A foreign boot id needs neither: its live pid and bus are no news.
	foreign := host.Standing{Contract: host.Contract, Pid: os.Getpid(), Boot: "boot-of-another-day", Bus: live, Port: port}
	for name, s := range map[string]host.Standing{"a reused pid": reused, "a dead pid": dead, "a foreign boot id": foreign} {
		root := t.TempDir()
		s.Root = root
		data, _ := json.Marshal(s)
		if err := os.MkdirAll(filepath.Join(root, host.Runtime), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(host.StandingPath(root), data, 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := host.ReadStanding(root); !errors.Is(err, host.ErrNotRunning) {
			t.Fatalf("%s reads as %v, and wants no core running", name, err)
		}
		c, err := host.Serve(host.Options{Root: root, Clock: newClock()})
		if err != nil {
			t.Fatalf("a core over %s answers %v, and wants to serve", name, err)
		}
		got, err := c.Standing()
		c.Stop("the case ends")
		<-c.Ended()
		if err != nil || got.Pid != os.Getpid() || got.Proc == "another-start" || got.Bus == live {
			t.Fatalf("over %s the standing file reads %+v, %v, and wants this core's", name, got, err)
		}
	}
}

// skipWithoutMark skips where the platform names no process's start: there
// the bus alone tells a reused pid, and the case's bus is live.
func skipWithoutMark(t *testing.T) {
	t.Helper()
	c := served(t, host.Options{Clock: newClock()})
	if s, err := c.Standing(); err != nil || s.Proc == "" {
		t.Skipf("this platform names no start of a process (%+v, %v)", s, err)
	}
}

// endedPid answers the pid of a process that ran and ended.
func endedPid(t *testing.T) int {
	t.Helper()
	ended := exec.Command(os.Args[0], "-test.run=^$")
	if err := ended.Run(); err != nil {
		t.Fatal(err)
	}
	return ended.ProcessState.Pid()
}

func tank(command []string) index.Wiring {
	return index.Wiring{
		Instances: []index.Instance{
			{Name: "pump", Component: "pump", Enabled: true, Config: map[string]index.ConfigValue{}, Command: command, CommandLine: 3, Line: 1},
			{Name: "gauge", Component: "gauge", Enabled: true, Config: map[string]index.ConfigValue{}, Line: 5},
		},
		Wires: []index.Wire{{Port: "pump.level", To: "tank/level", Line: 8}, {Port: "gauge.reading", To: "tank/reading", Line: 9}},
	}
}

// A placed instance runs in a process of its own with its bus, user and
// password; it commits its own names, the bus refuses it another's, and its
// names read stale once its lease lapses.
func TestAPlacedInstanceAttachesAndCommitsItsOwnNames(t *testing.T) {
	t.Parallel()
	clk := newClock()
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	c := served(t, host.Options{Clock: clk, Wiring: tank([]string{self, "-test.run=^$", placedArg}), Components: []*index.Component{pump, gauge}})
	core := as(t, c, bus.Core)
	values := make(chan *nats.Msg, 4)
	if _, err := core.ChanSubscribe(bus.Val+"tank.level", values); err != nil {
		t.Fatal(err)
	}
	_ = core.Flush()
	var level host.NameValue
	ask(t, core, bus.Get+"tank.level", nil, &level)
	if level.Provided {
		ask(t, core, bus.Get+"tank.level", nil, &level) // the process committed before the subscription stood
	} else {
		select {
		case <-values:
		case <-time.After(wait):
			t.Fatal("the placed pump commits nothing")
		}
		ask(t, core, bus.Get+"tank.level", nil, &level)
	}
	if level.Value != float64(7) || !level.Provided || level.Stale {
		t.Fatalf("tank/level reads %+v, and wants 7, provided and fresh: the bus refused the pump's commit as the gauge", level)
	}
	var reading host.NameValue
	ask(t, core, bus.Get+"tank.reading", nil, &reading)
	if reading.Provided {
		t.Fatalf("tank/reading reads %+v: the pump wrote the gauge's name", reading)
	}
	var h host.Health
	ask(t, core, host.HealthSubject, nil, &h)
	if len(h.Placements) != 1 || h.Placements[0].Instance != "pump" || !h.Placements[0].Running {
		t.Fatalf("the health shows the placements %+v, and wants the pump running", h.Placements)
	}
	clk.move(host.LeaseLapse + time.Second)
	ask(t, core, bus.Get+"tank.level", map[string]string{"name": "tank/level"}, &level)
	if !level.Stale {
		t.Fatalf("tank/level reads %+v after the pump's lease lapsed, and wants it stale", level)
	}
}

// A commit is checked against the writer's declaration: a value of another
// type is refused with its reason, and an unknown name answers an error.
func TestACommitOfTheWrongTypeIsRefused(t *testing.T) {
	t.Parallel()
	c := served(t, host.Options{Clock: newClock(), Wiring: tank(nil), Components: []*index.Component{pump, gauge}})
	core := as(t, c, bus.Core)
	var answer host.CommitAnswer
	ask(t, core, bus.Commit+"pump", map[string]any{"writes": []map[string]any{{"port": "level", "value": "high"}}}, &answer)
	if answer.Accepted || !strings.Contains(answer.Refused, "output level takes int") {
		t.Fatalf("a commit of a string to an int output answers %+v, and wants a refusal naming the type", answer)
	}
	ask(t, core, bus.Commit+"pump", map[string]any{"writes": []map[string]any{{"port": "level", "value": 3}}}, &answer)
	if !answer.Accepted || answer.Revision == 0 {
		t.Fatalf("a commit of an int answers %+v, and wants it accepted at a revision", answer)
	}
	var none host.NameValue
	ask(t, core, bus.Get+"tank.none", nil, &none)
	if none.Error == "" {
		t.Fatalf("a get of an unknown name answers %+v, and wants an error", none)
	}
}

// A placed instance that declares a derivation or a command is refused at start, with its wiring line.
func TestAPlacementTheCoreCannotRunIsRefused(t *testing.T) {
	t.Parallel()
	tally := index.Declare("tally", "Sums.", index.Derived("total", 0, "The sum.", func(struct{}) (int, error) { return 0, nil }))
	w := index.Wiring{Instances: []index.Instance{{Name: "tally", Component: "tally", Enabled: true, Config: map[string]index.ConfigValue{}, Command: []string{"tally"}, CommandLine: 3, Line: 1}},
		Wires: []index.Wire{{Port: "tally.total", To: "sum", Line: 5}}}
	if _, err := host.Serve(host.Options{Root: t.TempDir(), Clock: newClock(), Wiring: w, Components: []*index.Component{tally}}); err == nil || !strings.Contains(err.Error(), "wiring line 3: instance tally is placed") {
		t.Fatalf("a placed derivation starts with %v, and wants a refusal at its wiring line", err)
	}
}

// A hook posts its event and takes its session's lease; the core's answer is its effect.
func TestAHookPostTakesItsSessionsLease(t *testing.T) {
	t.Parallel()
	c := served(t, host.Options{})
	s, _ := c.Standing()
	a, err := host.Post(host.Wall{}, s.Root, "UserPromptSubmit", []byte(`{"session_id":"s1"}`), host.HookWait)
	if err != nil || a.Effect != "pass" {
		t.Fatalf("a hook's post answers %+v, %v, and wants the effect pass", a, err)
	}
	if h := c.Health(); len(h.Sessions) != 1 || h.Sessions[0] != "s1" {
		t.Fatalf("the health names the sessions %q, and wants [s1]", h.Sessions)
	}
}

// A hook fails open at once where no core runs and none is starting: given
// an hour to wait, it answers long before the hour, so it never waited for a
// core. The bound is the test's, not the hook's: runner variance cannot reach it.
func TestAHookWithNoCoreFailsOpenAtOnce(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	answered := make(chan error, 1)
	go func() {
		_, err := host.Post(host.Wall{}, root, "PreToolUse", []byte(`{}`), time.Hour)
		answered <- err
	}()
	select {
	case err := <-answered:
		if !errors.Is(err, host.ErrNotRunning) {
			t.Fatalf("a hook with no core answers %v, and wants ErrNotRunning", err)
		}
	case <-time.After(wait):
		t.Fatalf("a hook with no core and an hour's wait has not answered after %v: it waits for a core", wait)
	}
}

// looking is a wall clock that counts the looks at a start's claim (each
// one reads Now once the claim is found) and runs first on the first of them.
type looking struct {
	mu    sync.Mutex
	looks int
	first func()
}

func (l *looking) Now() time.Time {
	l.mu.Lock()
	l.looks++
	first := l.first
	l.first = nil
	l.mu.Unlock()
	if first != nil {
		first()
	}
	return time.Now()
}

func (l *looking) After(d time.Duration) <-chan time.Time { return time.After(d) }

func (l *looking) count() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.looks
}

// A hook waits for a starting core, by what it does and in which order, not
// by how long anything takes: with no claim it answers ErrNotRunning without
// looking; with a claim and no core it keeps looking until its wait ends; and
// a core that stands while the hook looks at its claim, the moment the
// claim's removal follows the standing file's write, is the core the hook
// reaches: the hook looks at the claim before it reads the standing file.
func TestAHookWaitsForAStartingCoreWithinItsWait(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	none := &looking{}
	if _, err := host.Post(none, root, "Stop", nil, wait); !errors.Is(err, host.ErrNotRunning) || none.count() != 0 {
		t.Fatalf("a hook with no claim answers %v after %d looks, and wants ErrNotRunning without looking", err, none.count())
	}
	if err := os.MkdirAll(filepath.Dir(host.ClaimPath(root)), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(host.ClaimPath(root), []byte("1\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	never := &looking{}
	if _, err := host.Post(never, root, "Stop", nil, 200*time.Millisecond); !errors.Is(err, host.ErrNotRunning) || never.count() < 2 {
		t.Fatalf("a hook whose core never comes up answers %v after %d looks, and wants ErrNotRunning once it looked again", err, never.count())
	}
	var c *host.Core
	stands := &looking{first: func() {
		var err error
		if c, err = host.Serve(host.Options{Root: root}); err != nil {
			t.Error(err)
		}
	}}
	a, err := host.Post(stands, root, "SessionStart", []byte(`{"session_id":"s1"}`), wait)
	if c != nil {
		c.Stop("the case ends")
		<-c.Ended()
	}
	if err != nil || a.Effect != "pass" {
		t.Fatalf("a hook for a core that stood while it looked answers %+v, %v, and wants the effect pass", a, err)
	}
}

// An event name that is no one word is refused before the bus sees it.
func TestAHookEventIsOneWord(t *testing.T) {
	t.Parallel()
	for _, event := range []string{"", "a.b", "a b", ">"} {
		if _, err := host.Post(host.Wall{}, t.TempDir(), event, nil, host.HookWait); !errors.Is(err, host.ErrNoEvent) {
			t.Fatalf("the event %q answers %v, and wants ErrNoEvent", event, err)
		}
	}
}

// checker answers its command with the hook's JSON it was handed, and fails on "fail".
var checker = index.Declare("checker", "Answers a hook.",
	index.Command(index.CommandDecl{
		Name: "checker check", Usage: "checker check --hook=JSON", Summary: "Answer a hook.", Help: "Says the hook's JSON back.",
		Group: "Fixtures", Class: index.Batch,
	}, func(_ struct{}, args []string) (index.Result, error) {
		if len(args) != 1 || !strings.HasPrefix(args[0], host.HookArg) {
			return index.Result{}, fmt.Errorf("checker check takes %sJSON, and was given %q", host.HookArg, args)
		}
		if strings.Contains(args[0], "fail") {
			return index.Result{}, errors.New("the check failed")
		}
		return index.Result{Text: `{"said": ` + strings.TrimPrefix(args[0], host.HookArg) + "}"}, nil
	}))

func checked(hooks ...index.Hook) index.Wiring {
	return index.Wiring{Instances: []index.Instance{{Name: "checker", Component: "checker", Enabled: true, Config: map[string]index.ConfigValue{}, Line: 1}}, Hooks: hooks}
}

// The command the wiring binds an event to answers it with the event's JSON,
// its text the hook's output; an event bound to none passes, and so does one
// whose command fails, with the reason.
func TestABoundHookIsAnsweredByItsCommand(t *testing.T) {
	t.Parallel()
	c := served(t, host.Options{Wiring: checked(index.Hook{Event: "Stop", Command: "checker check", Line: 3}), Components: []*index.Component{checker}})
	s, _ := c.Standing()
	a, err := host.Post(host.Wall{}, s.Root, "Stop", []byte(`{"session_id":"s1"}`), wait)
	if err != nil || a.Effect != host.Output || a.Output != `{"said": {"session_id":"s1"}}` {
		t.Fatalf("a bound Stop answers %+v, %v, and wants the command's text as its output", a, err)
	}
	if h := c.Health(); len(h.Sessions) != 1 {
		t.Fatalf("a bound hook takes its session's lease too: the health names %q, and wants [s1]", h.Sessions)
	}
	if a, err := host.Post(host.Wall{}, s.Root, "SubagentStop", []byte(`{}`), wait); err != nil || a.Effect != host.Pass || a.Error != "" {
		t.Fatalf("an unbound event answers %+v, %v, and wants pass", a, err)
	}
	if a, err := host.Post(host.Wall{}, s.Root, "Stop", []byte(`{"fail":1}`), wait); err != nil || a.Effect != host.Pass || !strings.Contains(a.Error, "the check failed") {
		t.Fatalf("a bound hook whose command fails answers %+v, %v, and wants pass with its reason", a, err)
	}
}

// A hook bound to a declared instance whose process has not attached passes
// with the reason, without waiting for the attach.
func TestAHookBoundToAnUnattachedInstancePassesAtOnce(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	dir := filepath.Join(root, "components", "remote")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	decl := "name = \"remote\"\ncontract = 1\nhelp = \"Answers a hook.\"\n\n[commands.\"remote check\"]\nusage = \"remote check\"\nsummary = \"Answer a hook.\"\ngroup = \"Fixtures\"\nhelp = \"Answers a hook.\"\nclass = \"batch\"\n"
	if err := os.WriteFile(filepath.Join(dir, index.DeclarationFile), []byte(decl), 0o600); err != nil {
		t.Fatal(err)
	}
	w := index.Wiring{Instances: []index.Instance{{Name: "remote", Component: "remote", Enabled: true, Config: map[string]index.ConfigValue{}, Line: 1}},
		Hooks: []index.Hook{{Event: "Stop", Command: "remote check", Line: 4}}}
	served(t, host.Options{Root: root, Wiring: w})
	began := time.Now()
	a, err := host.Post(host.Wall{}, root, "Stop", []byte(`{}`), wait)
	if err != nil || a.Effect != host.Pass || !strings.Contains(a.Error, "instance remote has not attached yet") {
		t.Fatalf("a hook bound to an unattached instance answers %+v, %v, and wants pass with the reason", a, err)
	}
	// Generous: the attach would wait host.AttachWait, 10 s.
	if took := time.Since(began); took > host.AttachWait/2 {
		t.Fatalf("a hook bound to an unattached instance took %v: it waited for the attach", took)
	}
}

// A hook bound to a command no instance declares is refused at the start, with its line.
func TestAHookBoundToNoCommandIsRefused(t *testing.T) {
	t.Parallel()
	_, err := host.Serve(host.Options{Root: t.TempDir(), Clock: newClock(), Wiring: checked(index.Hook{Event: "Stop", Command: "checker none", Line: 7}), Components: []*index.Component{checker}})
	if err == nil || !strings.Contains(err.Error(), `wiring line 7: hook Stop: no instance declares the command "checker none"`) {
		t.Fatalf("a hook bound to no command starts with %v, and wants a refusal at its line", err)
	}
}

// counter is a compiled command component; the usage test marks its instance
// ad hoc by dropping a component.toml under .se/components/counter/, so its
// call runs in the core (no placed process) and is still counted.
var counter = index.Declare("counter", "Counts.",
	index.Command(index.CommandDecl{
		Name: "counter run", Usage: "counter run", Summary: "Run.", Help: "Says ran.",
		Group: "Fixtures", Class: index.Batch, Session: true,
	}, func(_ struct{}, args []string) (index.Result, error) {
		return index.Result{Text: "ran"}, nil
	}))

// markAdHoc writes a component.toml under <root>/.se/components/<name>/, so the
// core reads that instance as ad hoc (usage.go adHocInstances).
func markAdHoc(t *testing.T, root, name string) {
	t.Helper()
	dir := filepath.Join(root, ".se", "components", name)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	decl := fmt.Sprintf("name = %q\ncontract = 1\nhelp = \"Ad hoc.\"\n", name)
	if err := os.WriteFile(filepath.Join(dir, index.DeclarationFile), []byte(decl), 0o600); err != nil {
		t.Fatal(err)
	}
}

// uses reads the ad hoc use log the core writes under root.
func uses(t *testing.T, root string) []map[string]any {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(root, host.UsageLog))
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		t.Fatal(err)
	}
	var out []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		if line == "" {
			continue
		}
		var m map[string]any
		if err := json.Unmarshal([]byte(line), &m); err != nil {
			t.Fatalf("use log line %q is no JSON: %v", line, err)
		}
		out = append(out, m)
	}
	return out
}

// A call to an ad hoc component's command is counted in the use log, against
// the session the core touched last; a call to a component that is not ad hoc
// writes nothing.
func TestAnAdHocCallIsCounted(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	markAdHoc(t, root, "counter")
	clk := newClock()
	w := index.Wiring{Instances: []index.Instance{
		{Name: "counter", Component: "counter", Enabled: true, Config: map[string]index.ConfigValue{}, Line: 1},
		{Name: "checker", Component: "checker", Enabled: true, Config: map[string]index.ConfigValue{}, Line: 2},
	}}
	c := served(t, host.Options{Root: root, Clock: clk, Wiring: w, Components: []*index.Component{counter, checker}})
	client := as(t, c, bus.Client)
	var effect host.HookAnswer
	ask(t, client, bus.Hook+"SessionStart", map[string]string{"session_id": "s1"}, &effect)
	clk.move(time.Minute)
	ask(t, client, bus.Hook+"SessionStart", map[string]string{"session_id": "s2"}, &effect)

	var ans host.CallAnswer
	ask(t, client, bus.Call+bus.Token("counter run"), map[string][]string{"args": {}}, &ans)
	if ans.Error != "" || ans.Text != "ran" {
		t.Fatalf("the ad hoc call answered %+v, and wants text ran", ans)
	}
	ask(t, client, bus.Call+bus.Token("checker check"), map[string][]string{"args": {host.HookArg + "{}"}}, &ans)

	records := uses(t, root)
	if len(records) != 1 {
		t.Fatalf("the use log holds %d records, and wants one (only the ad hoc call): %v", len(records), records)
	}
	r := records[0]
	if r["component"] != "counter" || r["path"] != ".se/components/counter" || r["session"] != "s2" {
		t.Fatalf("the use record is %v, and wants counter at .se/components/counter in session s2 (the newest lease)", r)
	}
	ask(t, client, bus.Call+bus.Token("counter run"), map[string][]string{"args": {}}, &ans)
	if records := uses(t, root); len(records) != 2 {
		t.Fatalf("a second ad hoc call makes %d records, and wants two (the log appends)", len(records))
	}
}

// The health lists an instance compiled into the core as attached, as the
// core started it with itself, and names the backend it chose at start; a
// switched-off instance is neither.
func TestTheHealthNamesCompiledInInstancesAndTheirBackends(t *testing.T) {
	t.Parallel()
	backend := index.Output("backend", "", "The backend chosen at start.")
	router := index.Declare("router", "Chooses a backend.", index.IO(), backend,
		index.Inlet(func(_ string, _ index.Reader, commit index.Commit) error {
			return commit(backend.Set("relay"))
		}))
	w := index.Wiring{Instances: []index.Instance{
		{Name: "github", Component: "router", Enabled: true, Config: map[string]index.ConfigValue{}, Line: 1},
		{Name: "spare", Component: "router", Enabled: false, Config: map[string]index.ConfigValue{}, Line: 4},
	}}
	c := served(t, host.Options{Clock: newClock(), Wiring: w, Components: []*index.Component{router}})
	h := c.Health()
	if len(h.Attached) != 1 || h.Attached[0] != "github" {
		t.Fatalf("the health lists %q as attached, and wants [github]", h.Attached)
	}
	if len(h.Backends) != 1 || h.Backends["github"] != "relay" {
		t.Fatalf("the health names the backends %v, and wants github: relay", h.Backends)
	}
	data, _ := json.Marshal(h)
	if !strings.Contains(string(data), `"backends":{"github":"relay"}`) {
		t.Fatalf("the health's JSON %s names no backends", data)
	}
}
