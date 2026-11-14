package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

// The door's waits.
const (
	// StartWait is how long a call waits for a core that is starting, then
	// answers the typed error "starting" with its remedy.
	StartWait = 5 * time.Second
	// Renew is how often the door renews its session's lease: each renewal
	// counts as an event, so the core's idle end never meets a live
	// connection.
	Renew = 30 * time.Second
	// look is how often the door looks for a core that is starting.
	look = 20 * time.Millisecond
	// leaseWait bounds one lease request.
	leaseWait = 2 * time.Second
	// callWait bounds one command's call: the core gives up a call whose
	// caller hangs up, so this only ends a call that runs on and on.
	callWait = 10 * time.Minute
)

// The kinds of a failed call, the "error" of its structured content.
const (
	// Starting: the core has not stood within StartWait.
	Starting = "starting"
	// NoCheckout: the door runs outside a checkout, where it starts no core.
	NoCheckout = "no-checkout"
	// Failed: the core ended at its start, or does not start.
	Failed = "failed"
	// CommandFailed: the core answered the call with an error.
	CommandFailed = "command-failed"
)

// Options are what a door serves.
type Options struct {
	// App is the application's name, the binary's: se, kern.
	App, Version string
	// Root is the checkout; Checkout is set where it holds .git. Outside a
	// checkout the door starts no core, and every call says so.
	Root     string
	Checkout bool
	// Catalog is what the core would serve (host.Catalog); CatalogErr why it
	// could not be read, which leaves the status tool alone.
	Catalog    index.Catalog
	CatalogErr error
	// Greeting are the names and read-only commands the greeting tool reads, in order.
	Greeting []string
	Core     Core
	// Session is the lease's session id; empty for one of the door's own.
	Session string
	// NoStart is why the door starts no core though it runs in a checkout,
	// such as no path to its own binary; every call answers it as failed.
	NoStart string
	// StartWait and Renew replace the built-in spans where set.
	StartWait, Renew time.Duration
	// PageLimit replaces the built-in PageLimit where set.
	PageLimit int
	// Log takes what the door says beside the protocol: stderr.
	Log io.Writer
}

// door is one served connection: its tools and the supervisor of its core.
type door struct {
	o      Options
	mu     sync.Mutex
	failed string // why the core does not start, once it said so
	// leased is set while the session's lease stands.
	leased atomic.Bool
	// pages are the answers that need more than one page, by tool and arguments.
	pages map[string][]string
}

// Serve serves the door on in and out, newline-delimited JSON-RPC as stdio
// carries it, until the client hangs up (EOF on in) or ctx ends, then returns
// the session's lease. Either handshake, server/discover (2026-07-28) or the
// legacy initialize, and tools/list never wait on the core: the supervisor
// starts or attaches to it beside the protocol.
func Serve(ctx context.Context, o Options, in io.ReadCloser, out io.WriteCloser) error {
	if o.StartWait == 0 {
		o.StartWait = StartWait
	}
	if o.Renew == 0 {
		o.Renew = Renew
	}
	if o.PageLimit == 0 {
		o.PageLimit = PageLimit
	}
	if o.Log == nil {
		o.Log = io.Discard
	}
	if o.Session == "" {
		o.Session = fmt.Sprintf("mcp-%d-%d", os.Getpid(), time.Now().UnixNano())
	}
	d := &door{o: o, pages: map[string][]string{}}
	server, err := d.server()
	if err != nil {
		fmt.Fprintf(o.Log, "%s mcp: %v\n", o.App, err)
		d.o.CatalogErr = err // the status tool names it
	}
	ctx, cancel := context.WithCancel(ctx)
	supervised := make(chan struct{})
	if o.Checkout && o.NoStart == "" {
		go func() { defer close(supervised); d.supervise(ctx) }()
	} else {
		close(supervised)
	}
	r := &hangUp{ReadCloser: in}
	err = server.Run(ctx, &sdk.IOTransport{Reader: r, Writer: out})
	cancel()
	<-supervised
	if r.eof.Load() || errors.Is(err, context.Canceled) {
		return nil // the client hung up: the door's normal end
	}
	return err
}

// hangUp is the client's side of the connection, which remembers its EOF:
// the SDK answers a hang-up as an error of its own.
type hangUp struct {
	io.ReadCloser
	eof atomic.Bool
}

func (h *hangUp) Read(p []byte) (int, error) {
	n, err := h.ReadCloser.Read(p)
	if errors.Is(err, io.EOF) {
		h.eof.Store(true)
	}
	return n, err
}

// server makes the SDK's server with the catalog's tools. A catalog the check
// refuses still serves the tools it made; the error goes to the log.
func (d *door) server() (*sdk.Server, error) {
	o := d.o
	s := sdk.NewServer(&sdk.Implementation{Name: o.App, Title: o.App, Version: o.Version}, &sdk.ServerOptions{
		// The tools are fixed for the connection: no tools/list_changed.
		Capabilities: &sdk.ServerCapabilities{Tools: &sdk.ToolCapabilities{}},
		Instructions: fmt.Sprintf("%s's core in %s, its read-only commands as tools. A tool that answers %q waits for the core's start: call it again in a few seconds.", o.App, o.Root, Starting),
	})
	err := o.CatalogErr
	var tools []Tool
	if err == nil {
		tools, err = Tools(o.App, o.Catalog, o.Greeting)
	} else {
		tools, _ = Tools(o.App, index.Catalog{}, nil)
	}
	for _, t := range tools {
		t := t
		destructive, open := false, t.OpenWorld
		tool := &sdk.Tool{
			Name: t.Name, Title: t.Title, Description: t.Description, InputSchema: schema(t),
			Annotations: &sdk.ToolAnnotations{Title: t.Title, ReadOnlyHint: true, DestructiveHint: &destructive, IdempotentHint: true, OpenWorldHint: &open},
		}
		s.AddTool(tool, func(ctx context.Context, req *sdk.CallToolRequest) (*sdk.CallToolResult, error) {
			return d.call(ctx, t, req.Params.Arguments), nil
		})
	}
	return s, err
}

// page is the argument that asks a later page of a long answer.
var page = map[string]any{"type": "integer", "minimum": 1, "description": fmt.Sprintf("the page of an answer longer than %d bytes, which says how many it has; 1 by default", PageLimit)}

// schema is a tool's input, generated from the catalog: none for status, the
// page for the greeting, and for a command tool the command, one its
// declarations name, its arguments and the page.
func schema(t Tool) map[string]any {
	if t.Name == StatusTool {
		return map[string]any{"type": "object", "properties": map[string]any{}, "additionalProperties": false}
	}
	if len(t.Commands) == 0 {
		return map[string]any{"type": "object", "properties": map[string]any{"page": page}, "additionalProperties": false}
	}
	names := make([]any, 0, len(t.Commands))
	for _, c := range t.Commands {
		names = append(names, c.Name)
	}
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"command": map[string]any{"type": "string", "enum": names, "description": "the command to run, as the tool's description names it"},
			"args":    map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "its arguments after its name, as its usage shows; none by default"},
			"page":    page,
		},
		"required":             []any{"command"},
		"additionalProperties": false,
	}
}

// supervise starts the core or attaches to it, takes the session's lease
// once it runs and renews it every Renew, starting it anew where it ended;
// as ctx ends, it returns the lease.
func (d *door) supervise(ctx context.Context) {
	leased := false
	defer func() {
		d.leased.Store(false)
		if leased {
			if err := d.o.Core.Lease(d.o.Session, true); err != nil {
				fmt.Fprintf(d.o.Log, "%s mcp: returning the lease: %v\n", d.o.App, err)
			}
		}
	}()
	started := false
	for {
		wait := look
		st, err := d.o.Core.Status()
		switch {
		case err != nil:
			fmt.Fprintf(d.o.Log, "%s mcp: status: %v\n", d.o.App, err)
			wait = d.o.Renew
		case st.State == host.StateRunning:
			if err := d.o.Core.Lease(d.o.Session, false); err != nil {
				fmt.Fprintf(d.o.Log, "%s mcp: lease: %v\n", d.o.App, err)
				leased = false
				d.leased.Store(false)
				break
			}
			leased, started = true, false
			d.leased.Store(true)
			d.fail("")
			wait = d.o.Renew
		case st.State == host.StateStopped && st.Died != "" && started:
			d.fail("the core ended at its start; it said:\n" + st.Died)
			wait = d.o.Renew
			started = false
		case st.State == host.StateStopped:
			leased = false
			d.leased.Store(false)
			if _, err := d.o.Core.Start(); err != nil {
				d.fail(err.Error())
				wait = d.o.Renew
				break
			}
			started = true
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}

func (d *door) fail(why string) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.failed = why
}

func (d *door) failure() string {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.failed
}

// await waits up to StartWait for a running core that holds the session's
// lease, and renews the lease; it answers the failed call's result where none
// runs by then. A core that runs and has not taken the lease by then is
// called all the same.
func (d *door) await(ctx context.Context) (host.Status, *sdk.CallToolResult) {
	o := d.o
	if o.NoStart != "" {
		return host.Status{}, failure(Failed, fmt.Sprintf("%s mcp starts no core in %s: %s", o.App, o.Root, o.NoStart),
			fmt.Sprintf("fix what it names and restart the server; run %s start --root %s to see it start", o.App, o.Root))
	}
	if !o.Checkout {
		return host.Status{}, failure(NoCheckout, fmt.Sprintf("%s mcp runs in %s, which is no checkout (no .git): it starts no core there", o.App, o.Root),
			"configure the server to run in the repository's folder (its cwd), or pass --root <checkout>")
	}
	end := time.Now().Add(o.StartWait)
	for {
		leased := d.leased.Load() // before the status, so a running core's health shows the lease
		st, err := o.Core.Status()
		running := err == nil && st.State == host.StateRunning
		if running && (leased || !time.Now().Before(end)) {
			// Every call renews the session's lease, beside the supervisor's renewal.
			if err := o.Core.Lease(o.Session, false); err != nil {
				fmt.Fprintf(o.Log, "%s mcp: renewing the lease: %v\n", o.App, err)
			}
			return st, nil
		}
		if why := d.failure(); why != "" {
			return st, failure(Failed, fmt.Sprintf("%s's core does not start in %s: %s", o.App, o.Root, why),
				fmt.Sprintf("read %s, fix what it names, then call again", host.LogPath(o.Root)))
		}
		if !time.Now().Before(end) || ctx.Err() != nil {
			return st, failure(Starting, fmt.Sprintf("%s's core is starting in %s and did not answer within %v", o.App, o.Root, o.StartWait),
				fmt.Sprintf("call again in a few seconds; the status tool says when it runs, and %s holds what it said", host.LogPath(o.Root)))
		}
		select {
		case <-ctx.Done():
		case <-time.After(look):
		}
	}
}

func failure(kind, message, remedy string) *sdk.CallToolResult {
	return &sdk.CallToolResult{
		IsError:           true,
		Content:           []sdk.Content{&sdk.TextContent{Text: fmt.Sprintf("%s: %s. Remedy: %s.", kind, message, remedy)}},
		StructuredContent: map[string]any{"error": kind, "message": message, "remedy": remedy},
	}
}

func text(s string, structured any) *sdk.CallToolResult {
	return &sdk.CallToolResult{Content: []sdk.Content{&sdk.TextContent{Text: s}}, StructuredContent: structured}
}

// call answers one tool call.
func (d *door) call(ctx context.Context, t Tool, raw json.RawMessage) *sdk.CallToolResult {
	switch {
	case t.Name == StatusTool:
		return d.status(ctx)
	}
	var in struct {
		Command string   `json:"command"`
		Args    []string `json:"args"`
		Page    int      `json:"page"`
	}
	if len(raw) > 0 {
		if err := json.Unmarshal(raw, &in); err != nil {
			return failure(CommandFailed, fmt.Sprintf("the arguments are no {\"command\", \"args\", \"page\"}: %v", err), "pass the command's name, its arguments as strings and the page as a number")
		}
	}
	if t.Greeting != nil {
		return d.paged(t.Name, in.Page, func() (string, *sdk.CallToolResult) { return d.greeting(ctx, t) })
	}
	known := false
	for _, c := range t.Commands {
		known = known || c.Name == in.Command
	}
	if !known {
		return failure(CommandFailed, fmt.Sprintf("%s offers no command %q", t.Name, in.Command), "name one its description lists")
	}
	key := strings.Join(append([]string{t.Name, in.Command}, in.Args...), "\x00")
	return d.paged(key, in.Page, func() (string, *sdk.CallToolResult) {
		if _, failed := d.await(ctx); failed != nil {
			return "", failed
		}
		a, err := d.run(ctx, in.Command, in.Args)
		if err != nil {
			return "", failure(CommandFailed, fmt.Sprintf("%s: %v", in.Command, err), "the status tool says whether the core still runs; call again")
		}
		if a.Error != "" {
			return "", failure(CommandFailed, fmt.Sprintf("%s: %s", in.Command, a.Error), "read the command's usage in the tool's description and its answer above")
		}
		return answerText(a), nil
	})
}

func (d *door) run(ctx context.Context, command string, args []string) (host.CallAnswer, error) {
	ctx, cancel := context.WithTimeout(ctx, callWait)
	defer cancel()
	return d.o.Core.Call(ctx, command, args)
}

func answerText(a host.CallAnswer) string {
	parts := append(append([]string{}, a.Lines...), a.Text)
	return strings.TrimSpace(strings.Join(parts, "\n"))
}

// status answers the core's state at once where it runs, else once it runs
// within StartWait, else the state it is in: never an error but outside a
// checkout or where the door starts no core (Options.NoStart).
func (d *door) status(ctx context.Context) *sdk.CallToolResult {
	st, failed := d.await(ctx)
	if failed != nil && (!d.o.Checkout || d.o.NoStart != "") {
		return failed
	}
	answer := map[string]any{"state": string(st.State), "root": d.o.Root}
	line := fmt.Sprintf("%s: %s in %s", d.o.App, st.State, d.o.Root)
	if st.State == host.StateRunning {
		h := st.Health
		answer["health"] = h
		line = fmt.Sprintf("%s: running in %s, pid %d, %d session(s), %d instance(s), %d placed", d.o.App, d.o.Root, h.Pid, len(h.Sessions), len(h.Instances), len(h.Placements))
	}
	if why := d.failure(); why != "" {
		answer["failed"] = why
		line += "; failed: " + why
	}
	if d.o.CatalogErr != nil {
		answer["catalog"] = d.o.CatalogErr.Error()
		line += "; the catalog: " + d.o.CatalogErr.Error()
	}
	data, _ := json.Marshal(answer)
	return text(line+"\n"+string(data), answer)
}

// greeting reads each entry: a name's value, a command's answer; a part that
// fails says why in its place.
func (d *door) greeting(ctx context.Context, t Tool) (string, *sdk.CallToolResult) {
	if _, failed := d.await(ctx); failed != nil {
		return "", failed
	}
	var b strings.Builder
	for _, e := range t.Greeting {
		fmt.Fprintf(&b, "## %s\n\n", e.Name)
		if e.Command {
			a, err := d.run(ctx, e.Name, nil)
			switch {
			case err != nil:
				fmt.Fprintf(&b, "failed: %v\n\n", err)
			case a.Error != "":
				fmt.Fprintf(&b, "failed: %s\n\n", a.Error)
			default:
				fmt.Fprintf(&b, "%s\n\n", answerText(a))
			}
			continue
		}
		v, err := d.o.Core.Get(ctx, e.Name)
		if err == nil && v.Error != "" {
			err = errors.New(v.Error)
		}
		if err != nil {
			fmt.Fprintf(&b, "failed: %v\n\n", err)
			continue
		}
		data, _ := json.MarshalIndent(v.Value, "", "  ")
		if !v.Provided {
			b.WriteString("Built-in: nothing is provided yet.\n\n")
		} else if v.Stale {
			b.WriteString("Stale: its writer stopped beating.\n\n")
		}
		fmt.Fprintf(&b, "```json\n%s\n```\n\n", data)
	}
	return strings.TrimSpace(b.String()), nil
}
