package mcp

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// fakeCore is the core as a test plays it: it stands once started, after
// standAfter looks at its status, and records every lease and call.
type fakeCore struct {
	mu         sync.Mutex
	running    bool
	standAfter int // looks at the status after the start until it stands; -1 never
	looks      int
	starts     int
	died       string
	leases     []string // "take <id>" or "end <id>"
	calls      []string
	answers    map[string]host.CallAnswer
	names      map[string]host.NameValue
}

func (f *fakeCore) Start() (host.Started, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.starts++
	if f.running {
		return host.Running, nil
	}
	f.looks = 0
	return host.Spawned, nil
}

func (f *fakeCore) Status() (host.Status, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.running && f.starts > 0 && f.standAfter >= 0 {
		f.looks++
		if f.looks > f.standAfter {
			f.running = true
		}
	}
	switch {
	case f.running:
		return host.Status{State: host.StateRunning, Health: host.Health{Pid: 7, Sessions: f.sessions()}}, nil
	case f.starts > 0 && f.died == "":
		return host.Status{State: host.StateStarting}, nil
	}
	return host.Status{State: host.StateStopped, Died: f.died}, nil
}

func (f *fakeCore) sessions() []string {
	held := map[string]bool{}
	for _, l := range f.leases {
		verb, id, _ := strings.Cut(l, " ")
		held[id] = verb == "take"
	}
	out := []string{}
	for id, on := range held {
		if on {
			out = append(out, id)
		}
	}
	return out
}

func (f *fakeCore) Lease(session string, end bool) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.running {
		return errors.New("no core runs")
	}
	verb := "take"
	if end {
		verb = "end"
	}
	f.leases = append(f.leases, verb+" "+session)
	return nil
}

func (f *fakeCore) Call(_ context.Context, command string, args []string) (host.CallAnswer, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, strings.TrimSpace(command+" "+strings.Join(args, " ")))
	if a, ok := f.answers[command]; ok {
		return a, nil
	}
	return host.CallAnswer{Error: "no such command"}, nil
}

func (f *fakeCore) Get(_ context.Context, name string) (host.NameValue, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if v, ok := f.names[name]; ok {
		return v, nil
	}
	return host.NameValue{Name: name, Error: "no name " + name}, nil
}

func (f *fakeCore) record() (leases, calls []string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string{}, f.leases...), append([]string{}, f.calls...)
}

// client is the fake client: it writes JSON-RPC lines to the door and reads
// its answers, as a host does over stdio.
type client struct {
	t    *testing.T
	in   *io.PipeWriter
	out  *bufio.Reader
	id   int
	done chan error
}

func open(t *testing.T, o Options) *client {
	t.Helper()
	inR, inW := io.Pipe()
	outR, outW := io.Pipe()
	c := &client{t: t, in: inW, out: bufio.NewReader(outR), done: make(chan error, 1)}
	go func() {
		err := Serve(context.Background(), o, inR, outW)
		outW.Close()
		c.done <- err
	}()
	t.Cleanup(func() { c.in.Close() })
	return c
}

// ask sends a request and answers its result, failing on an error answer.
func (c *client) ask(method string, params any) json.RawMessage {
	c.t.Helper()
	c.id++
	c.send(map[string]any{"jsonrpc": "2.0", "id": c.id, "method": method, "params": params})
	for {
		line, err := c.out.ReadBytes('\n')
		if err != nil {
			c.t.Fatalf("%s: the door answered nothing: %v", method, err)
		}
		var m struct {
			ID     *int            `json:"id"`
			Result json.RawMessage `json:"result"`
			Error  json.RawMessage `json:"error"`
		}
		if err := json.Unmarshal(line, &m); err != nil {
			c.t.Fatalf("%s: the door wrote no JSON-RPC line: %q", method, line)
		}
		if m.ID == nil || *m.ID != c.id {
			continue // a notification
		}
		if m.Error != nil {
			c.t.Fatalf("%s answers the error %s", method, m.Error)
		}
		return m.Result
	}
}

func (c *client) send(m any) {
	c.t.Helper()
	data, _ := json.Marshal(m)
	if _, err := c.in.Write(append(data, '\n')); err != nil {
		c.t.Fatal(err)
	}
}

func (c *client) initialize() json.RawMessage {
	c.t.Helper()
	r := c.ask("initialize", map[string]any{"protocolVersion": "2025-06-18", "capabilities": map[string]any{},
		"clientInfo": map[string]any{"name": "fake", "version": "0"}})
	c.send(map[string]any{"jsonrpc": "2.0", "method": "notifications/initialized"})
	return r
}

type listed struct {
	Tools []struct {
		Name        string         `json:"name"`
		Description string         `json:"description"`
		InputSchema map[string]any `json:"inputSchema"`
		Annotations struct {
			ReadOnly    bool  `json:"readOnlyHint"`
			Destructive *bool `json:"destructiveHint"`
			OpenWorld   *bool `json:"openWorldHint"`
		} `json:"annotations"`
	} `json:"tools"`
}

type called struct {
	IsError bool `json:"isError"`
	Content []struct {
		Text string `json:"text"`
	} `json:"content"`
	Structured map[string]any `json:"structuredContent"`
}

func (c *client) call(tool string, args map[string]any) called {
	c.t.Helper()
	var r called
	if err := json.Unmarshal(c.ask("tools/call", map[string]any{"name": tool, "arguments": args}), &r); err != nil {
		c.t.Fatal(err)
	}
	return r
}

// hangUp closes the client's side and waits for the door to end.
func (c *client) hangUp() {
	c.t.Helper()
	c.in.Close()
	select {
	case err := <-c.done:
		if err != nil {
			c.t.Fatalf("the door ends on EOF with %v, and wants none", err)
		}
	case <-time.After(10 * time.Second):
		c.t.Fatal("the door runs on after EOF")
	}
}

// catalog is a core's catalog: a component with a read-only command and a
// batch one, and a derived name.
func catalog(t *testing.T) index.Catalog {
	t.Helper()
	comp, err := index.ParseDeclaration([]byte(`name = "desk"
contract = 1
help = "The desk: what waits on it."

[outputs.due]
type = "int"
builtin = 0
help = "How many items are due."

[commands."desk list"]
usage = "desk list [--all]"
summary = "list the desk"
group = "Desk"
help = "list the desk"
class = "interactive"
mcp = "Lists what waits on the desk; use it to see what to do next."

[commands."desk clear"]
usage = "desk clear"
summary = "clear the desk"
group = "Desk"
help = "clear the desk"
class = "batch"
`))
	if err != nil {
		t.Fatal(err)
	}
	w, err := index.ParseWiring([]byte("[instances.desk]\ncomponent = \"desk\"\n"))
	if err != nil {
		t.Fatal(err)
	}
	c, err := index.Collect(w, comp)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func options(core Core, c index.Catalog) Options {
	return Options{App: "app", Version: "1.2.3", Root: "/work/checkout", Checkout: true, Catalog: c, Core: core,
		Session: "s1", Greeting: []string{"desk/due", "desk list", "absent/name"}, StartWait: 300 * time.Millisecond, Renew: time.Hour}
}

// initialize and tools/list answer while the core never stands: from the
// catalog, without waiting on it.
func TestInitializeAndListAnswerWhileTheCoreStarts(t *testing.T) {
	core := &fakeCore{standAfter: -1}
	c := open(t, options(core, catalog(t)))
	var init struct {
		ServerInfo struct{ Name, Version string } `json:"serverInfo"`
	}
	if err := json.Unmarshal(c.initialize(), &init); err != nil || init.ServerInfo.Name != "app" || init.ServerInfo.Version != "1.2.3" {
		t.Fatalf("initialize answers %+v (%v), and wants the application app 1.2.3", init, err)
	}
	var l listed
	if err := json.Unmarshal(c.ask("tools/list", map[string]any{}), &l); err != nil {
		t.Fatal(err)
	}
	var names []string
	byName := map[string]int{}
	for i, tool := range l.Tools {
		names = append(names, tool.Name)
		byName[tool.Name] = i
		if !tool.Annotations.ReadOnly || tool.Annotations.Destructive == nil || *tool.Annotations.Destructive || tool.Description == "" {
			t.Errorf("tool %s carries %+v and %q, and wants read-only, not destructive, and a description", tool.Name, tool.Annotations, tool.Description)
		}
	}
	if strings.Join(names, " ") != "desk greeting status" {
		t.Fatalf("tools/list answers %v, and wants desk, greeting and status", names)
	}
	desk := l.Tools[byName["desk"]]
	if !strings.Contains(desk.Description, "`desk list`: Lists what waits on the desk; use it to see what to do next. Usage: `desk list [--all]`") ||
		strings.Contains(desk.Description, "desk clear") {
		t.Fatalf("desk's description is %q, and wants its read-only command with its mcp description and usage, no batch one", desk.Description)
	}
	enum := desk.InputSchema["properties"].(map[string]any)["command"].(map[string]any)["enum"]
	if fmt.Sprint(enum) != "[desk list]" {
		t.Fatalf("desk's command enum is %v, and wants [desk list]", enum)
	}
	greeting := l.Tools[byName["greeting"]].Description
	if !strings.Contains(greeting, "`desk/due`: How many items are due.") || !strings.Contains(greeting, "`desk list`: Lists") || strings.Contains(greeting, "absent") {
		t.Fatalf("the greeting's description is %q, and wants the name and the command it reads, without the one the catalog lacks", greeting)
	}
	c.hangUp()
}

// A call made before the core stands waits StartWait, then answers the typed
// error "starting" with its remedy; once it stands the call goes through, and
// the lease is taken before it.
func TestACallWaitsForTheCoreThenAnswersStarting(t *testing.T) {
	core := &fakeCore{standAfter: -1, answers: map[string]host.CallAnswer{"desk list": {Text: "two items", Lines: []string{"reading"}}}}
	c := open(t, options(core, catalog(t)))
	c.initialize()
	r := c.call("desk", map[string]any{"command": "desk list"})
	if !r.IsError || r.Structured["error"] != Starting || !strings.Contains(fmt.Sprint(r.Structured["remedy"]), "call again in a few seconds") {
		t.Fatalf("a call before the core stands answers %+v, and wants the error starting with its remedy", r)
	}
	core.mu.Lock()
	core.standAfter, core.looks = 0, 0
	core.mu.Unlock()
	r = c.call("desk", map[string]any{"command": "desk list", "args": []string{"--all"}})
	if r.IsError || len(r.Content) != 1 || r.Content[0].Text != "reading\ntwo items" {
		t.Fatalf("a call once the core stands answers %+v, and wants its lines and text", r)
	}
	leases, calls := core.record()
	if len(leases) == 0 || leases[0] != "take s1" || strings.Join(calls, ";") != "desk list --all" {
		t.Fatalf("the core saw the leases %v and the calls %v, and wants the lease taken, then desk list --all", leases, calls)
	}
	c.hangUp()
	if leases, _ := core.record(); leases[len(leases)-1] != "end s1" {
		t.Fatalf("the door's leases are %v after EOF, and want the last returned", leases)
	}
}

// The door starts no second core where one runs: it attaches and takes the lease.
func TestTheDoorAttachesToARunningCore(t *testing.T) {
	core := &fakeCore{running: true}
	c := open(t, options(core, catalog(t)))
	c.initialize()
	r := c.call("status", map[string]any{})
	if r.IsError || r.Structured["state"] != "running" || !strings.Contains(r.Content[0].Text, "running in /work/checkout, pid 7, 1 session(s)") {
		t.Fatalf("status answers %+v, and wants the running core with the door's session", r)
	}
	c.hangUp()
	core.mu.Lock()
	defer core.mu.Unlock()
	if core.starts != 0 {
		t.Fatalf("the door started %d core(s) where one ran, and wants none", core.starts)
	}
}

// The greeting reads its names and runs its commands; a part that fails says
// why in its place. A command tool refuses a command it does not offer.
func TestTheGreetingReadsItsParts(t *testing.T) {
	core := &fakeCore{running: true,
		names:   map[string]host.NameValue{"desk/due": {Name: "desk/due", Value: 3, Provided: true}},
		answers: map[string]host.CallAnswer{"desk list": {Error: "exit code 1"}}}
	c := open(t, options(core, catalog(t)))
	c.initialize()
	r := c.call("greeting", map[string]any{})
	text := r.Content[0].Text
	if r.IsError || !strings.Contains(text, "## desk/due\n\n```json\n3\n```") || !strings.Contains(text, "## desk list\n\nfailed: exit code 1") {
		t.Fatalf("the greeting answers %q, and wants desk/due's value and desk list's failure", text)
	}
	r = c.call("desk", map[string]any{"command": "desk clear"})
	if !r.IsError || r.Structured["error"] != CommandFailed {
		t.Fatalf("desk answers %+v for a batch command, and wants it refused", r)
	}
	if _, calls := core.record(); strings.Join(calls, ";") != "desk list" {
		t.Fatalf("the core saw the calls %v, and wants only the greeting's desk list", calls)
	}
	c.hangUp()
}

// A core that ends at its start is named in the call's error, with its log.
func TestACoreThatDiesAtItsStartIsNamed(t *testing.T) {
	core := &fakeCore{standAfter: -1, died: "wiring line 3: no component x"}
	o := options(core, catalog(t))
	o.StartWait = 10 * time.Second
	c := open(t, o)
	c.initialize()
	r := c.call("desk", map[string]any{"command": "desk list"})
	if !r.IsError || r.Structured["error"] != Failed || !strings.Contains(fmt.Sprint(r.Structured["message"]), "no component x") {
		t.Fatalf("a call to a core that died at its start answers %+v, and wants the error failed with what it said", r)
	}
	c.hangUp()
}

// Outside a checkout the door starts nothing, and every call says so.
func TestOutsideACheckoutTheDoorStartsNothing(t *testing.T) {
	core := &fakeCore{}
	o := options(core, catalog(t))
	o.Checkout = false
	c := open(t, o)
	c.initialize()
	if r := c.call("status", map[string]any{}); !r.IsError || r.Structured["error"] != NoCheckout {
		t.Fatalf("status outside a checkout answers %+v, and wants the error no-checkout", r)
	}
	c.hangUp()
	if core.starts != 0 {
		t.Fatalf("the door started a core outside a checkout")
	}
}

// The catalog check refuses an interactive command without an MCP
// description, in the declaration and in the door's tools alike.
func TestTheCatalogCheckRefusesACommandWithoutAnMCPDescription(t *testing.T) {
	_, err := index.ParseDeclaration([]byte(`name = "desk"
contract = 1
help = "h"

[commands."desk list"]
usage = "desk list"
summary = "s"
group = "g"
help = "h"
class = "interactive"
`))
	if err == nil || !strings.Contains(err.Error(), `command "desk list" is interactive and has no mcp description`) {
		t.Fatalf("the declaration answers %v, and wants the command without an mcp description refused", err)
	}
	c := catalog(t)
	for i := range c.Commands {
		c.Commands[i].MCP = "" // as a catalog might hand it, past its declaration
	}
	if _, err := Tools("app", c, nil); err == nil || !strings.Contains(err.Error(), "has no mcp description") {
		t.Fatalf("Tools answers %v, and wants the command without an mcp description refused", err)
	}
	if _, err := Tools("app", catalog(t), []string{"desk clear"}); err == nil || !strings.Contains(err.Error(), "is a batch command") {
		t.Fatalf("Tools answers %v for a batch greeting entry, and wants it refused", err)
	}
}
