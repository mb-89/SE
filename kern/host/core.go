package host

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"reflect"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/index"
	"github.com/nats-io/nats.go"
)

// The built-in spans of the core's lifetime (docs/go-core.md, "Lifetime: bound to the session").
const (
	// Grace is how long the core runs on once no session holds a lease.
	Grace = 60 * time.Second
	// Idle is how long the core runs without any event.
	Idle = 30 * time.Minute
	// LeaseLapse is how long a component's lease holds after its last beat: three beats of Beat.
	LeaseLapse = 3 * Beat
	// Beat is how often a placed component beats on lease.<i>.
	Beat = 5 * time.Second
	// checkEvery is how often the core looks whether it ends.
	checkEvery = time.Second
	// HangUp is how long a stop waits for its asker to hang up before the bus goes.
	HangUp = time.Second
)

// The core's own names and commands on the bus.
const (
	// HealthSubject answers the core's health.
	HealthSubject = bus.Get + "core.health"
	// StopSubject stops the core; it answers the core's pid first.
	StopSubject = bus.Call + "core.stop"
	// AbandonSubject gives up a call its asker runs, {"call": <its reply
	// subject>}; it answers whether one ran (docs/go-core.md "A call given up").
	AbandonSubject = bus.Call + "core.abandon"
)

// SessionEnd is the hook event that returns a session's lease.
const SessionEnd = "SessionEnd"

// PostToolUse is the hook event that follows a tool's run: the core counts
// the ad hoc scripts a shell tool ran (scripts.go).
const PostToolUse = "PostToolUse"

// Options are what a core starts with.
type Options struct {
	// Root is the checkout the core serves; its standing file lies under it.
	Root string
	// Wiring and Components make the index; an instance with a Command is placed in a process of its own.
	Wiring     index.Wiring
	Components []*index.Component
	// Clock is the time the core reads; the wall clock where none is given.
	Clock Clock
	// Grace, Idle and LeaseLapse override the built-in spans where set.
	Grace, Idle, LeaseLapse time.Duration
	// StepWait and CallBeat override the built-in waits of a call where set.
	StepWait, CallBeat time.Duration
	// Log takes what the core and its placed processes say; none where nil.
	Log io.Writer
}

// Core is a running core.
type Core struct {
	o      Options
	ix     *index.Index
	bus    *bus.Bus
	nc     *nats.Conn
	pid    int
	start  time.Time
	writer map[string]string // a name, or a family, to the instance that writes it
	types  map[string]map[string]reflect.Type
	placed map[string]bool
	comps  []*index.Component
	// declared are the instances of components declared by their
	// component.toml alone; attached closes once an instance's process attached.
	declared map[string]*index.Component
	attached map[string]chan struct{}
	// hooks are the wiring's bound events: an event to the instance and the command that answer it.
	hooks map[string]index.CommandInfo
	// adhoc are the instances whose component is declared under .se/components/,
	// by instance name: their calls are counted in the use log (usage.go).
	adhoc map[string]adHoc

	mu         sync.Mutex
	sessions   map[string]time.Time
	emptySince time.Time
	lastEvent  time.Time
	beats      map[string]time.Time
	procs      []*placement
	prev       map[string]uint64
	reason     string
	// calls are the running calls, by reply subject, and how each is given up.
	calls map[string]context.CancelCauseFunc

	done     chan struct{}
	stopOnce sync.Once
	ended    chan struct{}
}

type placement struct {
	instance string
	cmd      *exec.Cmd
	exited   chan struct{}
	err      error
}

// Serve starts a core: it checks the catalog and starts the index, stands the
// bus with a user for each instance, answers the core's subjects, writes the
// standing file, removes the start's claim and starts the placed instances.
// It refuses where another core already runs in the checkout.
func Serve(o Options) (*Core, error) {
	if o.Clock == nil {
		o.Clock = Wall{}
	}
	if o.Grace == 0 {
		o.Grace = Grace
	}
	if o.Idle == 0 {
		o.Idle = Idle
	}
	if o.LeaseLapse == 0 {
		o.LeaseLapse = LeaseLapse
	}
	if o.StepWait == 0 {
		o.StepWait = StepWait
	}
	if o.CallBeat == 0 {
		o.CallBeat = CallBeat
	}
	if o.Log == nil {
		o.Log = io.Discard
	}
	if s, err := ReadStanding(o.Root); err == nil {
		return nil, fmt.Errorf("kern serve: a core already runs in %s, pid %d (%s)", o.Root, s.Pid, StandingPath(o.Root))
	}
	decls, err := declarations(o.Root, o.Wiring, o.Components)
	if err != nil {
		return nil, err
	}
	comps := append(append([]*index.Component{}, o.Components...), decls...)
	ix, err := index.Start(o.Wiring, comps...)
	if err != nil {
		return nil, fmt.Errorf("kern serve: %w", err)
	}
	c := &Core{
		o: o, ix: ix, pid: os.Getpid(), start: o.Clock.Now(), comps: comps,
		declared: map[string]*index.Component{}, attached: map[string]chan struct{}{},
		writer: map[string]string{}, types: map[string]map[string]reflect.Type{}, placed: map[string]bool{},
		sessions: map[string]time.Time{}, beats: map[string]time.Time{}, prev: map[string]uint64{}, calls: map[string]context.CancelCauseFunc{},
		done: make(chan struct{}), ended: make(chan struct{}), hooks: map[string]index.CommandInfo{},
	}
	for _, h := range o.Wiring.Hooks {
		info, ok := ix.Catalog().Command(h.Command)
		if !ok {
			return nil, fmt.Errorf("kern serve: wiring line %d: hook %s: no instance declares the command %q", h.Line, h.Event, h.Command)
		}
		c.hooks[h.Event] = info
	}
	names := make([]instanceName, 0, len(o.Wiring.Instances))
	for _, in := range o.Wiring.Instances {
		names = append(names, instanceName{Name: in.Name, Component: in.Component})
	}
	c.adhoc = adHocInstances(o.Root, names)
	c.emptySince, c.lastEvent = c.start, c.start
	if err := c.place(); err != nil {
		return nil, err
	}
	var instances []bus.Instance
	for _, in := range ix.Catalog().Instances {
		instances = append(instances, bus.Instance{Name: in.Name, IO: in.IO})
		c.types[in.Name] = map[string]reflect.Type{}
		for _, out := range in.Outputs {
			c.writer[out.Name] = in.Name
			c.types[in.Name][out.Port.Port] = out.Type
		}
	}
	if c.bus, err = bus.Start(instances); err != nil {
		return nil, fmt.Errorf("kern serve: %w", err)
	}
	if c.nc, err = bus.Dial(c.bus.URL(), bus.Core, c.bus.Users()[bus.Core]); err != nil {
		c.bus.Close()
		return nil, fmt.Errorf("kern serve: %w", err)
	}
	byName := map[string]*index.Component{}
	for _, comp := range decls {
		byName[comp.Name()] = comp
	}
	for _, in := range o.Wiring.Instances {
		if comp := byName[in.Component]; comp != nil {
			comp.SetRemote(remote{c: c, inst: in.Name})
			c.declared[in.Name] = comp
			c.attached[in.Name] = make(chan struct{})
		}
	}
	ix.OnRun(c.runInstance)
	if err := c.answer(); err != nil {
		c.close()
		return nil, fmt.Errorf("kern serve: %w", err)
	}
	standing := Standing{
		Contract: Contract, Pid: c.pid, Root: o.Root, Bus: c.bus.URL(), Port: c.bus.Port(),
		Started: c.start.UTC(), Users: c.bus.Users(),
	}
	if err := writeStanding(o.Root, standing); err != nil {
		c.close()
		return nil, fmt.Errorf("kern serve: the standing file: %w", err)
	}
	_ = os.Remove(ClaimPath(o.Root))
	if err := c.spawnPlaced(standing); err != nil {
		c.Stop(err.Error())
		<-c.ended
		return nil, fmt.Errorf("kern serve: %w", err)
	}
	go c.watch()
	return c, nil
}

// place refuses a placement the core cannot run out of process yet: a placed
// instance commits and beats over the bus, and a derivation or a command of
// its runs in the core, so it declares neither.
func (c *Core) place() error {
	comps := map[string]*index.Component{}
	for _, comp := range c.comps {
		comps[comp.Name()] = comp
	}
	for _, in := range c.o.Wiring.Instances {
		if len(in.Command) == 0 || !in.Enabled {
			continue
		}
		comp := comps[in.Component]
		if !comp.Declared() && (len(comp.Derivations()) > 0 || len(comp.Commands()) > 0) {
			return fmt.Errorf("kern serve: wiring line %d: instance %s is placed, and its component %s declares a derivation or a command, which runs in the core until a placed process answers run and cmd", in.CommandLine, in.Name, in.Component)
		}
		c.placed[in.Name] = true
	}
	return nil
}

// answer subscribes the core to its subjects: names, commits, leases, hooks and its own commands.
func (c *Core) answer() error {
	subs := []struct {
		subject string
		fn      nats.MsgHandler
	}{
		{HealthSubject, func(m *nats.Msg) { c.reply(m, c.Health()) }},
		{StopSubject, func(m *nats.Msg) {
			c.event()
			c.reply(m, map[string]any{"pid": c.pid})
			// The asker hangs up once it has the answer; one that stays on delays the stop by HangUp at most.
			if m.Reply != "" {
				c.bus.Unheard(m.Reply, HangUp)
			}
			c.Stop("asked to stop")
		}},
		{bus.Get + ">", c.get},
		{bus.Commit + ">", c.commit},
		{bus.Lease + ">", func(m *nats.Msg) { c.beat(bus.Name(strings.TrimPrefix(m.Subject, bus.Lease))) }},
		{bus.Hook + ">", c.hook},
		{bus.In + ">", c.inputs},
		{bus.Call + ">", c.call},
	}
	for _, s := range subs {
		if _, err := c.nc.Subscribe(s.subject, s.fn); err != nil {
			return err
		}
	}
	for name := range c.writer {
		name := name
		cancel, err := c.ix.Subscribe(name, func(v index.Value) { c.push(name, v) })
		if err != nil {
			continue // a family pushes nothing by its own name
		}
		go func() { <-c.done; cancel() }()
	}
	return c.nc.Flush()
}

func (c *Core) reply(m *nats.Msg, v any) {
	data, err := json.Marshal(v)
	if err != nil {
		data, _ = json.Marshal(map[string]string{"error": err.Error()})
	}
	_ = m.Respond(data)
}

// NameValue is what get.<name> answers.
type NameValue struct {
	Name     string `json:"name"`
	Value    any    `json:"value"`
	Provided bool   `json:"provided"`
	// Stale is set where the name's writer is placed and its lease has lapsed.
	Stale    bool   `json:"stale,omitempty"`
	Revision uint64 `json:"revision"`
	Error    string `json:"error,omitempty"`
}

// get answers a name: from the body where it names one, since a family's key
// may hold a dot, else from the subject's tokens.
func (c *Core) get(m *nats.Msg) {
	if m.Subject == HealthSubject {
		return
	}
	name := bus.Name(strings.TrimPrefix(m.Subject, bus.Get))
	var asked struct {
		Name string `json:"name"`
	}
	if len(m.Data) > 0 && json.Unmarshal(m.Data, &asked) == nil && asked.Name != "" {
		name = asked.Name
	}
	snap := c.ix.Snapshot()
	v, err := snap.Read(name)
	if err != nil {
		c.reply(m, NameValue{Name: name, Revision: snap.Revision(), Error: err.Error()})
		return
	}
	c.reply(m, NameValue{Name: name, Value: v.V, Provided: v.Provided, Stale: c.stale(name), Revision: snap.Revision()})
}

// stale says whether a name's writer is placed and its lease has lapsed.
func (c *Core) stale(name string) bool {
	inst, ok := c.writer[name]
	for n, i := range c.writer {
		if !ok && strings.HasPrefix(name, n+"/") {
			inst, ok = i, true
		}
	}
	return ok && c.placed[inst] && c.lapsed(inst)
}

// CommitWrite is one write of a commit as it rides the bus.
type CommitWrite struct {
	Port  string          `json:"port"`
	Key   string          `json:"key,omitempty"`
	Value json.RawMessage `json:"value,omitempty"`
	Gone  bool            `json:"gone,omitempty"`
}

// CommitAnswer is what commit.<i> answers.
type CommitAnswer struct {
	Accepted bool   `json:"accepted"`
	Revision uint64 `json:"revision,omitempty"`
	Refused  string `json:"refused,omitempty"`
}

// commit applies an instance's writes, each value read as its port's type.
// The bus lets only the instance itself publish on commit.<i>.
func (c *Core) commit(m *nats.Msg) {
	inst := bus.Name(strings.TrimPrefix(m.Subject, bus.Commit))
	refuse := func(format string, a ...any) { c.reply(m, CommitAnswer{Refused: fmt.Sprintf(format, a...)}) }
	types, ok := c.types[inst]
	if !ok {
		refuse("no instance %s", inst)
		return
	}
	var body struct {
		Attach *Attach       `json:"attach"`
		Writes []CommitWrite `json:"writes"`
	}
	if err := json.Unmarshal(m.Data, &body); err != nil {
		refuse("commit.%s: the body is no JSON of writes: %v", bus.Subject(inst), err)
		return
	}
	if body.Attach != nil {
		if err := c.attach(inst, *body.Attach); err != nil {
			refuse("%v", err)
			return
		}
		c.beat(inst)
		c.reply(m, CommitAnswer{Accepted: true, Revision: c.ix.Snapshot().Revision()})
		return
	}
	if c.declared[inst] != nil && !c.isAttached(inst) {
		refuse("instance %s has not attached: its process commits {\"attach\": {\"contract\": %d, \"hash\": ...}} first", inst, Contract)
		return
	}
	writes := make([]index.Write, 0, len(body.Writes))
	for _, w := range body.Writes {
		write := index.Write{Port: w.Port, Key: w.Key, Gone: w.Gone}
		if t, ok := types[w.Port]; ok && !w.Gone {
			v := reflect.New(t)
			if err := json.Unmarshal(w.Value, v.Interface()); err != nil {
				refuse("instance %s: output %s takes %s: %v", inst, w.Port, t, err)
				return
			}
			write.Value = v.Elem().Interface()
		}
		writes = append(writes, write)
	}
	if err := c.ix.Commit(inst, writes...); err != nil {
		refuse("%v", err)
		return
	}
	c.beat(inst)
	c.reply(m, CommitAnswer{Accepted: true, Revision: c.ix.Snapshot().Revision()})
}

// push publishes a name's new value on val.<name>, with the revision it had before.
func (c *Core) push(name string, v index.Value) {
	rev := c.ix.Snapshot().Revision()
	c.mu.Lock()
	prev := c.prev[name]
	c.prev[name] = rev
	c.mu.Unlock()
	data, err := json.Marshal(map[string]any{"name": name, "value": v.V, "provided": v.Provided, "revision": rev, "previous": prev})
	if err == nil {
		_ = c.nc.Publish(bus.Val+bus.Subject(name), data)
	}
}

func (c *Core) beat(inst string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.beats[inst] = c.o.Clock.Now()
}

func (c *Core) event() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.lastEvent = c.o.Clock.Now()
}

// The effects hook.<event> answers.
const (
	// Pass is the effect of an event no command answers: the host goes on.
	Pass = "pass"
	// Output is the effect of an event a command answered: its text is the host's hook output.
	Output = "output"
)

// HookArg is the one argument the command bound to an event is run with:
// HookArg followed by the event's JSON as the host gave it.
const HookArg = "--hook="

// HookAnswer is what hook.<event> answers: the effect on the host, the
// output of the command that answered it, or why the bound command did not.
type HookAnswer struct {
	Effect string `json:"effect"`
	Output string `json:"output,omitempty"`
	Error  string `json:"error,omitempty"`
	// Context is what the components that tell the agent say on the event,
	// which the hook hands the agent; empty for none.
	Context string `json:"context,omitempty"`
}

// hook takes a host's hook event: each renews the session's lease, and
// SessionEnd returns it. Every instance that hears the host's events is
// handed it first; what one refuses goes to the log, and the hook passes.
// Where the wiring binds the event to a command, the command answers it, run
// with HookArg and the event's JSON; where its instance's process has not
// attached yet, or the command fails, the event passes with the reason, at
// once rather than waiting for the attach.
func (c *Core) hook(m *nats.Msg) {
	event := strings.TrimPrefix(m.Subject, bus.Hook)
	var body struct {
		Session string `json:"session_id"`
	}
	_ = json.Unmarshal(m.Data, &body)
	now := c.o.Clock.Now()
	c.mu.Lock()
	c.lastEvent = now
	if body.Session != "" {
		if event == SessionEnd {
			delete(c.sessions, body.Session)
			if len(c.sessions) == 0 {
				c.emptySince = now
			}
		} else {
			c.sessions[body.Session] = now
		}
	}
	c.mu.Unlock()
	if event == PostToolUse {
		// After the answer: the hook does not wait on the count's one git call,
		// and the next event, handled in turn, finds it written.
		defer countScripts(c.o.Root, m.Data, now)
	}
	if err := c.ix.Hear(event, m.Data); err != nil {
		fmt.Fprintln(c.o.Log, err)
	}
	told := strings.Join(c.ix.Tell(event, m.Data), "\n\n")
	h, bound := c.hooks[event]
	if !bound {
		c.reply(m, HookAnswer{Effect: Pass, Context: told})
		return
	}
	if _, declared := c.declared[h.Instance]; declared && !c.isAttached(h.Instance) {
		c.reply(m, HookAnswer{Effect: Pass, Error: fmt.Sprintf("hook %s: instance %s has not attached yet", event, h.Instance)})
		return
	}
	payload := string(m.Data)
	go func() { // a command may take its time; the next event does not wait for it
		r, err := c.ix.Call(h.Name, HookArg+payload)
		if err != nil {
			c.reply(m, HookAnswer{Effect: Pass, Error: fmt.Sprintf("hook %s: %v", event, err)})
			return
		}
		c.reply(m, HookAnswer{Effect: Output, Output: r.Text})
	}()
}

// Health is what get.core.health answers.
type Health struct {
	Contract   int              `json:"contract"`
	Pid        int              `json:"pid"`
	Bus        string           `json:"bus"`
	Started    time.Time        `json:"started"`
	Revision   uint64           `json:"revision"`
	Sessions   []string         `json:"sessions"`
	Instances  []string         `json:"instances"`
	Placements []PlacementState `json:"placements"`
	// Attached are the declared instances whose process has attached.
	Attached []string `json:"attached"`
}

// PlacementState is one placed instance as the health shows it.
type PlacementState struct {
	Instance string `json:"instance"`
	Pid      int    `json:"pid"`
	Running  bool   `json:"running"`
	Stale    bool   `json:"stale"`
	Exit     string `json:"exit,omitempty"`
}

// Health answers the core as it stands.
func (c *Core) Health() Health {
	h := Health{Contract: Contract, Pid: c.pid, Bus: c.bus.URL(), Started: c.start.UTC(), Revision: c.ix.Snapshot().Revision(), Sessions: []string{}, Instances: []string{}, Placements: []PlacementState{}}
	h.Attached = []string{}
	for _, in := range c.ix.Catalog().Instances {
		h.Instances = append(h.Instances, in.Name)
		if c.isAttached(in.Name) {
			h.Attached = append(h.Attached, in.Name)
		}
	}
	c.mu.Lock()
	for s := range c.sessions {
		h.Sessions = append(h.Sessions, s)
	}
	procs := append([]*placement{}, c.procs...)
	c.mu.Unlock()
	sort.Strings(h.Sessions)
	for _, p := range procs {
		st := PlacementState{Instance: p.instance, Pid: p.cmd.Process.Pid}
		select {
		case <-p.exited:
			st.Exit = fmt.Sprint(p.err)
		default:
			st.Running = true
		}
		st.Stale = c.lapsed(p.instance)
		h.Placements = append(h.Placements, st)
	}
	return h
}

// lapsed says whether an instance's lease has lapsed: no beat within the
// lapse, counted from the core's start for one that never beat.
func (c *Core) lapsed(inst string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	last, ok := c.beats[inst]
	if !ok {
		last = c.start
	}
	return c.o.Clock.Now().Sub(last) > c.o.LeaseLapse
}

// spawnPlaced starts each placed instance's process with its bus, user and password.
func (c *Core) spawnPlaced(s Standing) error {
	for _, in := range c.o.Wiring.Instances {
		if !c.placed[in.Name] {
			continue
		}
		cmd := exec.Command(in.Command[0], in.Command[1:]...)
		cmd.Dir = c.o.Root
		cmd.Env = append(os.Environ(), bus.EnvBus+"="+s.Bus, bus.EnvUser+"="+in.Name, bus.EnvToken+"="+s.Users[in.Name])
		cmd.Stdout, cmd.Stderr = c.o.Log, c.o.Log
		if err := cmd.Start(); err != nil {
			return fmt.Errorf("wiring line %d: instance %s: its command does not start: %w", in.CommandLine, in.Name, err)
		}
		p := &placement{instance: in.Name, cmd: cmd, exited: make(chan struct{})}
		go func() {
			p.err = cmd.Wait()
			close(p.exited)
		}()
		c.mu.Lock()
		c.procs = append(c.procs, p)
		c.mu.Unlock()
	}
	return nil
}

// Check ends the core where no session has held a lease for the grace, or
// where no event came for the idle span.
func (c *Core) Check() {
	now := c.o.Clock.Now()
	c.mu.Lock()
	var reason string
	switch {
	case len(c.sessions) == 0 && now.Sub(c.emptySince) >= c.o.Grace:
		reason = fmt.Sprintf("no session has held a lease for %v", c.o.Grace)
	case now.Sub(c.lastEvent) >= c.o.Idle:
		reason = fmt.Sprintf("no event for %v", c.o.Idle)
	}
	c.mu.Unlock()
	if reason != "" {
		c.Stop(reason)
	}
}

func (c *Core) watch() {
	for {
		select {
		case <-c.done:
			return
		case <-c.o.Clock.After(checkEvery):
			c.Check()
		}
	}
}

// Stop ends the core: its placed processes, its bus and its standing file.
// Ended closes once all are down.
func (c *Core) Stop(reason string) {
	c.stopOnce.Do(func() {
		c.mu.Lock()
		c.reason = reason
		c.mu.Unlock()
		close(c.done)
		go func() {
			c.close()
			close(c.ended)
		}()
	})
}

func (c *Core) close() {
	c.mu.Lock()
	procs := append([]*placement{}, c.procs...)
	c.mu.Unlock()
	for _, p := range procs {
		_ = p.cmd.Process.Kill()
		<-p.exited
	}
	if c.nc != nil {
		// The last answers, the stop's among them, reach the server before it goes.
		_ = c.nc.FlushTimeout(time.Second)
		c.nc.Close()
	}
	if c.bus != nil {
		c.bus.Close()
	}
	dropStanding(c.o.Root, c.pid)
}

// Ended closes once the core is down.
func (c *Core) Ended() <-chan struct{} { return c.ended }

// Reason answers why the core ended, or nothing while it runs.
func (c *Core) Reason() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.reason
}

// Standing answers what the core's standing file says.
func (c *Core) Standing() (Standing, error) {
	s, err := ReadStanding(c.o.Root)
	if err != nil {
		return Standing{}, err
	}
	if s.Pid != c.pid {
		return Standing{}, errors.New("the standing file names another core")
	}
	return s, nil
}
