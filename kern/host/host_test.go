package host_test

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
	"github.com/nats-io/nats.go"
)

// wait is how long a case waits on an event that comes within milliseconds.
const wait = 10 * time.Second

// placedArg makes this test binary a placed component's process.
const placedArg = "kern-test-placed"

func TestMain(m *testing.M) {
	if os.Args[len(os.Args)-1] == placedArg {
		os.Exit(placed())
	}
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

// A client stops the core on call.core.stop, and hears its pid first.
func TestAClientStopsTheCore(t *testing.T) {
	t.Parallel()
	c := served(t, host.Options{Clock: newClock()})
	var said map[string]int
	ask(t, as(t, c, bus.Client), host.StopSubject, nil, &said)
	if said["pid"] != os.Getpid() {
		t.Fatalf("the stop answers %v, and wants the core's pid %d", said, os.Getpid())
	}
	ended(t, c, "asked to stop")
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

// A hook fails open at once where no core runs and none is starting.
func TestAHookWithNoCoreFailsOpenAtOnce(t *testing.T) {
	t.Parallel()
	began := time.Now()
	_, err := host.Post(host.Wall{}, t.TempDir(), "PreToolUse", []byte(`{}`), host.HookWait)
	if !errors.Is(err, host.ErrNotRunning) {
		t.Fatalf("a hook with no core answers %v, and wants ErrNotRunning", err)
	}
	if took := time.Since(began); took > 50*time.Millisecond {
		t.Fatalf("a hook with no core took %v, and should not wait for one", took)
	}
}

// A hook waits for a core whose start's claim stands, within its wait, and
// gives up when the wait is out.
func TestAHookWaitsForAStartingCoreWithinItsWait(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Dir(host.ClaimPath(root)), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(host.ClaimPath(root), []byte("1\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	began := time.Now()
	if _, err := host.Post(host.Wall{}, root, "Stop", nil, 30*time.Millisecond); !errors.Is(err, host.ErrNotRunning) {
		t.Fatalf("a hook whose core never comes up answers %v, and wants ErrNotRunning", err)
	}
	if took := time.Since(began); took < 30*time.Millisecond {
		t.Fatalf("a hook gave a starting core %v, and should wait out its 30ms", took)
	}
	up := make(chan *host.Core, 1)
	go func() {
		time.Sleep(20 * time.Millisecond)
		c, err := host.Serve(host.Options{Root: root})
		if err != nil {
			t.Error(err)
		}
		up <- c
	}()
	a, err := host.Post(host.Wall{}, root, "SessionStart", []byte(`{"session_id":"s1"}`), wait)
	if c := <-up; c != nil {
		c.Stop("the case ends")
		<-c.Ended()
	}
	if err != nil || a.Effect != "pass" {
		t.Fatalf("a hook for a starting core answers %+v, %v, and wants the effect pass", a, err)
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
