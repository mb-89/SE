package mcp

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
	"unicode/utf8"

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
	// meta is the _meta every request carries once discover named the
	// protocol of 2026-07-28, which holds no session.
	meta map[string]any
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
	if p, ok := params.(map[string]any); ok && c.meta != nil {
		with := map[string]any{"_meta": c.meta}
		for k, v := range p {
			with[k] = v
		}
		params = with
	}
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

// discover is the handshake of the MCP spec of 2026-07-28: server/discover,
// no notification after it, and every later request carries the protocol,
// the client and its capabilities in its _meta.
func (c *client) discover() json.RawMessage {
	c.t.Helper()
	c.meta = map[string]any{
		"io.modelcontextprotocol/protocolVersion":    "2026-07-28",
		"io.modelcontextprotocol/clientInfo":         map[string]any{"name": "fake", "version": "0"},
		"io.modelcontextprotocol/clientCapabilities": map[string]any{},
	}
	return c.ask("server/discover", map[string]any{})
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

// catalog is a core's catalog: a component with a read-only command, an
// interactive one that writes and a batch one, and a derived name.
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
read-only = true
mcp = "Lists what waits on the desk; use it to see what to do next."

[commands."desk sync"]
usage = "desk sync"
summary = "fetch the desk and list it"
group = "Desk"
help = "fetch the desk and list it"
class = "interactive"
mcp = "Fetches the desk; interactive, and it writes, so it is declared not read-only."

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
		strings.Contains(desk.Description, "desk clear") || strings.Contains(desk.Description, "desk sync") {
		t.Fatalf("desk's description is %q, and wants its read-only command with its mcp description and usage, none that writes", desk.Description)
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

// The door speaks both handshakes, server/discover of 2026-07-28 and the
// legacy initialize, each answered from the catalog while the core never
// stands, and tools/list at once after either, with the same tools.
func TestBothHandshakesAnswerWhileTheCoreStarts(t *testing.T) {
	tools := map[string]string{}
	for _, handshake := range []string{"server/discover", "initialize"} {
		c := open(t, options(&fakeCore{standAfter: -1}, catalog(t)))
		var answer struct {
			ProtocolVersion   string                                    `json:"protocolVersion"`
			SupportedVersions []string                                  `json:"supportedVersions"`
			ServerInfo        struct{ Name, Version string }            `json:"serverInfo"`
			Meta              map[string]struct{ Name, Version string } `json:"_meta"`
			Capabilities      struct {
				Tools *struct{} `json:"tools"`
			} `json:"capabilities"`
		}
		var raw json.RawMessage
		if handshake == "initialize" {
			raw = c.initialize()
		} else {
			raw = c.discover()
		}
		if err := json.Unmarshal(raw, &answer); err != nil {
			t.Fatal(err)
		}
		server := answer.ServerInfo
		if handshake == "server/discover" {
			server = answer.Meta["io.modelcontextprotocol/serverInfo"]
			if !strings.Contains(strings.Join(answer.SupportedVersions, " "), "2026-07-28") {
				t.Fatalf("server/discover answers the versions %v, and wants 2026-07-28 among them", answer.SupportedVersions)
			}
		} else if answer.ProtocolVersion != "2025-06-18" {
			t.Fatalf("initialize answers the protocol %q, and wants the client's 2025-06-18", answer.ProtocolVersion)
		}
		if server.Name != "app" || server.Version != "1.2.3" || answer.Capabilities.Tools == nil {
			t.Fatalf("%s answers %s, and wants the application app 1.2.3 with tools", handshake, raw)
		}
		var l listed
		if err := json.Unmarshal(c.ask("tools/list", map[string]any{}), &l); err != nil {
			t.Fatal(err)
		}
		var names []string
		for _, tool := range l.Tools {
			names = append(names, tool.Name)
		}
		tools[handshake] = strings.Join(names, " ")
		c.hangUp()
	}
	if tools["initialize"] != "desk greeting status" || tools["server/discover"] != tools["initialize"] {
		t.Fatalf("tools/list answers %v by handshake, and wants desk, greeting and status after either", tools)
	}
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
	leases, calls := core.record()
	if strings.Join(calls, ";") != "desk list" {
		t.Fatalf("the core saw the calls %v, and wants only the greeting's desk list", calls)
	}
	// The supervisor's lease, then one renewal per call that reached the core.
	if n := strings.Count(strings.Join(leases, ";"), "take s1"); n < 2 {
		t.Fatalf("the core saw the leases %v, and wants each call to renew the session's", leases)
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

// The door's catalog check refuses an interactive command without an MCP
// description, which the declaration reads, and a batch command in the
// greeting; the door serves the tools it made all the same, and its status
// names the refusal.
func TestTheCatalogCheckRefusesACommandWithoutAnMCPDescription(t *testing.T) {
	comp, err := index.ParseDeclaration([]byte(`name = "desk"
contract = 1
help = "h"

[commands."desk list"]
usage = "desk list"
summary = "s"
group = "g"
help = "h"
class = "interactive"
read-only = true
mcp = "Lists the desk."
`))
	if err != nil {
		t.Fatal(err)
	}
	if got := comp.Commands()[0]; got.MCP != "Lists the desk." || !got.ReadOnly {
		t.Fatalf("the declaration reads %+v, and wants desk list read-only, its mcp description Lists the desk.", got)
	}
	c := catalog(t)
	for i := range c.Commands {
		c.Commands[i].MCP = "" // as a catalog might hand it, past its declaration
	}
	tools, err := Tools("app", c, nil)
	if err == nil || !strings.Contains(err.Error(), `command "desk list" of instance desk is read-only and has no mcp description`) {
		t.Fatalf("Tools answers %v, and wants the command without an mcp description refused", err)
	}
	if len(tools) != 1 || tools[0].Name != StatusTool {
		t.Fatalf("Tools makes %+v beside its refusal, and wants the status tool alone", tools)
	}
	o := options(&fakeCore{running: true}, c)
	o.Greeting = nil
	cl := open(t, o)
	cl.initialize()
	if r := cl.call("status", map[string]any{}); !strings.Contains(fmt.Sprint(r.Structured["catalog"]), "has no mcp description") {
		t.Fatalf("status answers %+v, and wants the catalog check's refusal named", r)
	}
	cl.hangUp()
	for _, entry := range []string{"desk clear", "desk sync"} {
		if _, err := Tools("app", catalog(t), []string{entry}); err == nil || !strings.Contains(err.Error(), "not declared read-only") {
			t.Fatalf("Tools answers %v for the greeting entry %s, and wants a command not declared read-only refused", err, entry)
		}
	}
}

// An answer longer than the page limit comes in pages below it, each asked
// by "page"; a later page is read from the kept answer, not run again.
func TestALongAnswerComesInPages(t *testing.T) {
	long := strings.Repeat("a line of the desk, about forty bytes\n", 100) // 3,800 bytes
	core := &fakeCore{running: true, answers: map[string]host.CallAnswer{"desk list": {Text: long}}}
	o := options(core, catalog(t))
	o.PageLimit = 1000
	c := open(t, o)
	c.initialize()
	var got strings.Builder
	pages := 0
	for page := 1; ; page++ {
		r := c.call("desk", map[string]any{"command": "desk list", "page": page})
		if r.IsError || r.Structured["page"] != float64(page) {
			t.Fatalf("page %d answers %+v, and wants that page", page, r)
		}
		body, _, _ := strings.Cut(r.Content[0].Text, "\n\n[page ")
		if len(body) > 1000 {
			t.Fatalf("page %d carries %d bytes, and wants at most the limit, 1000", page, len(body))
		}
		got.WriteString(body)
		pages = int(r.Structured["pages"].(float64))
		if page == pages {
			break
		}
		if !strings.Contains(r.Content[0].Text, fmt.Sprintf("\"page\": %d for the rest", page+1)) {
			t.Fatalf("page %d says %q, and wants the next page named", page, r.Content[0].Text)
		}
	}
	if pages < 4 || got.String() != strings.TrimSpace(long) {
		t.Fatalf("the %d pages join to %d bytes, and want the whole answer, %d bytes", pages, got.Len(), len(strings.TrimSpace(long)))
	}
	if _, calls := core.record(); len(calls) != 1 {
		t.Fatalf("the core ran %v for the pages, and wants the command run once", calls)
	}
	if r := c.call("desk", map[string]any{"command": "desk list", "page": 99}); !r.IsError {
		t.Fatalf("a page past the last answers %+v, and wants it refused", r)
	}
	c.hangUp()
}

// pages cuts at line ends where a line fits, and inside a line only at a
// rune's boundary.
func TestPagesCutAtLinesAndRunes(t *testing.T) {
	if got := pages("ab\ncd\n", 3); strings.Join(got, "|") != "ab\n|cd\n" {
		t.Fatalf("pages answers %q, and wants a page per line", got)
	}
	for _, p := range pages(strings.Repeat("ä", 10), 5) {
		if !utf8.ValidString(p) || len(p) > 5 {
			t.Fatalf("pages cut %q, and wants whole runes within the limit", p)
		}
	}
}

// Where the door starts no core, such as without a path to its binary, it
// serves all the same, and every call answers why.
func TestADoorThatStartsNoCoreServesAndSaysWhy(t *testing.T) {
	core := &fakeCore{}
	o := options(core, catalog(t))
	o.NoStart = "no path to this binary"
	c := open(t, o)
	c.initialize()
	for _, tool := range []string{"status", "desk"} {
		r := c.call(tool, map[string]any{"command": "desk list"})
		if !r.IsError || r.Structured["error"] != Failed || !strings.Contains(fmt.Sprint(r.Structured["message"]), "no path to this binary") {
			t.Fatalf("%s answers %+v, and wants the error failed naming why", tool, r)
		}
	}
	c.hangUp()
	if core.starts != 0 {
		t.Fatalf("the door started a core it should not start")
	}
}

// A tool is named in snake_case: an instance's dashes read as underscores.
func TestAToolIsNamedInSnakeCase(t *testing.T) {
	c := catalog(t)
	for i := range c.Instances {
		c.Instances[i].Name = "front-desk"
	}
	for i := range c.Commands {
		c.Commands[i].Instance = "front-desk"
	}
	tools, err := Tools("app", c, nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := tools[len(tools)-1]; got.Name != "front_desk" || got.Instance != "front-desk" {
		t.Fatalf("the instance front-desk's tool is %+v, and wants the name front_desk", got)
	}
}

// golden rewrites testdata/door.json from what the door answers now.
var golden = flag.Bool("golden", false, "rewrite testdata/door.json from the door's answers")

// The door's tools and one answer are its public face: the tools tools/list
// names and a call of desk answer, byte for byte as JSON, what
// testdata/door.json holds, after either handshake, so a bump of the SDK or
// of Go that changes either fails here. Rewrite it with
// go test ./mcp -run TestTheToolsAndAnAnswerStayTheSame -golden, only where
// the change is meant.
func TestTheToolsAndAnAnswerStayTheSame(t *testing.T) {
	for _, handshake := range []string{"initialize", "server/discover"} {
		t.Run(strings.ReplaceAll(handshake, "/", "-"), func(t *testing.T) { theToolsAndAnAnswer(t, handshake) })
	}
}

func theToolsAndAnAnswer(t *testing.T, handshake string) {
	core := &fakeCore{running: true, answers: map[string]host.CallAnswer{"desk list": {Text: "two items", Lines: []string{"reading"}}}}
	c := open(t, options(core, catalog(t)))
	if handshake == "initialize" {
		c.initialize()
	} else {
		c.discover()
	}
	var list struct {
		Tools any `json:"tools"`
	}
	// The door's parts of the answer, not the protocol's around them (the
	// _meta and resultType of 2026-07-28).
	var answer struct {
		Content    any `json:"content"`
		IsError    any `json:"isError,omitempty"`
		Structured any `json:"structuredContent,omitempty"`
	}
	if err := json.Unmarshal(c.ask("tools/list", map[string]any{}), &list); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(c.ask("tools/call", map[string]any{"name": "desk", "arguments": map[string]any{"command": "desk list"}}), &answer); err != nil {
		t.Fatal(err)
	}
	// The tools of tools/list, not its envelope: the protocol's own fields
	// beside them (cacheScope and ttlMs) are the SDK's.
	answers := map[string]any{"tools/list tools": list.Tools, "tools/call desk": answer}
	c.hangUp()
	got, err := json.MarshalIndent(answers, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	got = append(got, '\n')
	path := filepath.Join("testdata", "door.json")
	if *golden && handshake == "initialize" {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, got, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != strings.ReplaceAll(string(want), "\r\n", "\n") {
		t.Fatalf("the door answers\n%s\nand wants what %s holds:\n%s", got, filepath.ToSlash(path), want)
	}
}
