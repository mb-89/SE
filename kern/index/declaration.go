package index

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"regexp"
	"sort"
	"strings"
	"sync/atomic"

	"github.com/pelletier/go-toml/v2"
)

// Contract is the component contract's version this index speaks. A
// declaration names it as contract = 1, and a process that attaches with
// another is refused.
const Contract = 1

// DeclarationFile is a component's declaration, beside its code.
const DeclarationFile = "component.toml"

// Hash is the declaration hash a component's process attaches with: the
// SHA-256 of its component.toml's bytes, line ends read as LF, written
// sha256:<hex>. Its bytes, not what they parse to, so Go and Python, which
// format numbers differently, answer one hash.
func Hash(data []byte) string {
	sum := sha256.Sum256([]byte(strings.ReplaceAll(string(data), "\r\n", "\n")))
	return "sha256:" + hex.EncodeToString(sum[:])
}

// Remote is a declared component's own process, as the core reaches it over
// the bus: it answers each step of a command and each request on a verb.
type Remote interface {
	// Command runs one step; say, where set, takes each progress line the
	// step says, live where the process says it before its answer. Once ctx
	// is done it stops waiting, tells the process (Stop) and fails the step.
	Command(ctx context.Context, name string, step Step, say func(line string)) (Answer, error)
	// Stop tells the process that the core gave up the call of the command,
	// so nothing waits on it: no continuation of it runs, and no step of it
	// is answered.
	Stop(name, call, reason string)
	// Serve hands one request on a verb to the process, and stops waiting
	// for its answer once ctx is done.
	Serve(ctx context.Context, verb string, req json.RawMessage) (json.RawMessage, error)
}

// Step is one step of a command a declared component's process runs: the
// first carries the arguments and the inputs by local port, each later one
// the answers its continuation reads, in the order of its requests.
type Step struct {
	Call    string          `json:"call"`
	Step    int             `json:"step"`
	Args    []string        `json:"args,omitempty"`
	Inputs  map[string]any  `json:"inputs,omitempty"`
	Answers json.RawMessage `json:"answers,omitempty"`
}

// Answer is what a declared component's process answers a step: its result,
// with Then set where a continuation reads the answers of its requests. The
// step's lines ride say.<i>.<call> as it says them, never its answer: Lines
// holds those the core heard (kern/README.md "A component in Python" holds
// its row to these fields).
type Answer struct {
	Text     string      `json:"text"`
	Lines    []string    `json:"-"`
	Writes   []WireWrite `json:"writes,omitempty"`
	Requests []WireAsk   `json:"requests,omitempty"`
	Then     bool        `json:"then,omitempty"`
	Error    string      `json:"error,omitempty"`
}

// WireWrite is one write as it rides the bus.
type WireWrite struct {
	Port  string          `json:"port"`
	Key   string          `json:"key,omitempty"`
	Value json.RawMessage `json:"value,omitempty"`
	Gone  bool            `json:"gone,omitempty"`
}

// WireAsk is one request as it rides the bus.
type WireAsk struct {
	Port  string          `json:"port"`
	Value json.RawMessage `json:"value"`
}

type declared struct {
	hash     string
	remote   Remote
	calls    atomic.Int64 // a call's id, so two calls running side by side hear their own words
	inShapes map[string]string
}

// Declared says whether the component is declared by its component.toml
// alone, and so runs in its own process.
func (c *Component) Declared() bool { return c.decl != nil }

// DeclarationHash is a declared component's hash, which its process attaches with.
func (c *Component) DeclarationHash() string {
	if c.decl == nil {
		return ""
	}
	return c.decl.hash
}

// SetRemote hands a declared component the process that runs it.
func (c *Component) SetRemote(r Remote) {
	if c.decl != nil {
		c.decl.remote = r
	}
}

// ReadDeclaration reads a component.toml.
func ReadDeclaration(path string) (*Component, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("declaration: %w", err)
	}
	c, err := ParseDeclaration(data)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return c, nil
}

// ParseDeclaration makes a component from a component.toml's text: the
// component in another language that the core runs in a process of its own.
// Its derivations and its commands read every input and config key it
// declares; it refuses an unknown key, a missing help, built-in value or
// command field, and another contract version, as the catalog check would.
//
//	name = "tally"
//	contract = 1
//	io = false
//	help = "..."
//	[inputs]
//	numbers = "[int]"                      # port = type
//	[outputs.total]
//	type = "int"; builtin = 0; derived = true; family = false; help = "..."
//	[config.scale]
//	type = "int"; builtin = 1; help = "..."
//	[commands."tally note"]
//	usage = "..."; summary = "..."; group = "..."; help = "..."; class = "batch"; session = true
//	mcp = "..."   # when to use it, as the MCP door offers it; an interactive command needs one
//	[requests.post]
//	type = "string"; answer = "int"; help = "..."
//	[verbs.append]                         # an I/O component's
//	type = "string"; answer = "int"; help = "..."
//
// A type is int, float, string, bool, [T] for a list of T, or a named JSON
// shape such as github.issues, which Go reads as any.
func ParseDeclaration(data []byte) (*Component, error) {
	var doc map[string]any
	if err := toml.Unmarshal(data, &doc); err != nil {
		return nil, fmt.Errorf("declaration: %v", err)
	}
	d := &decoder{}
	name := d.str(doc, "name", true)
	help := d.str(doc, "help", false)
	c := &Component{
		name: name, help: help,
		inputs: map[string]reflect.Type{}, outputs: map[string]*Port{}, config: map[string]*Port{},
		derive: map[string]*derivation{}, commands: map[string]*command{}, requests: map[string]*RequestDecl{},
		verbs: map[string]*verb{}, decl: &declared{hash: Hash(data), inShapes: map[string]string{}},
	}
	d.keys(doc, "", "name", "contract", "io", "help", "inputs", "outputs", "config", "commands", "requests", "verbs")
	if v, ok := doc["contract"].(int64); !ok || v != Contract {
		d.fail("contract is %v, and this core speaks contract = %d", doc["contract"], Contract)
	}
	if v, ok := doc["io"]; ok {
		b, isBool := v.(bool)
		if !isBool {
			d.fail("io is true or false")
		}
		c.io = b
	}
	if !pathName(name) {
		c.fail("a component needs a name of letters, digits and dashes, or <group>/<component>, not %q", name)
	}
	if strings.TrimSpace(help) == "" {
		c.fail("component %s has no help", name)
	}
	var reads []string
	inputs := d.table(doc, "inputs")
	for _, port := range sortedKeys(inputs) {
		s, _ := inputs[port].(string)
		t, shape, err := TypeOf(s)
		if err != nil {
			d.fail("input %s: %v", port, err)
			continue
		}
		if !portName(port) {
			c.fail("input %q needs a local name of letters, digits and dashes", port)
		}
		c.inputs[port] = t
		c.decl.inShapes[port] = shape
		reads = append(reads, port)
	}
	config := d.table(doc, "config")
	for _, key := range sortedKeys(config) {
		t := d.sub(config, key, "config."+key, "type", "builtin", "help")
		p, ok := d.port(t, "config."+key, key)
		if !ok {
			continue
		}
		c.addConfig(p)
		c.inputs[ConfigPrefix+key] = p.Type
		reads = append(reads, ConfigPrefix+key)
	}
	in := inputStruct{ports: reads}
	outputs := d.table(doc, "outputs")
	for _, port := range sortedKeys(outputs) {
		where := "outputs." + port
		t := d.sub(outputs, port, where, "type", "builtin", "help", "derived", "family")
		p, ok := d.port(t, where, port)
		if !ok {
			continue
		}
		p.Derived, p.Family = d.flag(t, where, "derived"), d.flag(t, where, "family")
		if p.Derived && p.Family {
			d.fail("%s: a derivation writes no family", where)
		}
		c.addOutput(p)
		if p.Derived {
			c.derive[port] = &derivation{in: in}
		}
	}
	commands := d.table(doc, "commands")
	for _, n := range sortedKeys(commands) {
		where := fmt.Sprintf("commands.%q", n)
		t := d.sub(commands, n, where, "usage", "summary", "group", "help", "class", "session", "mcp")
		k := &command{decl: CommandDecl{
			Name: n, Usage: d.str(t, "usage", false), Summary: d.str(t, "summary", false),
			Group: d.str(t, "group", false), Help: d.str(t, "help", false),
			Class: Class(d.str(t, "class", false)), Session: d.flag(t, where, "session"),
			MCP: d.str(t, "mcp", false),
		}, in: in}
		c.addCommand(k)
	}
	for _, kind := range []string{"requests", "verbs"} {
		tab := d.table(doc, kind)
		for _, n := range sortedKeys(tab) {
			where := kind + "." + n
			t := d.sub(tab, n, where, "type", "answer", "help")
			req, reqShape, err := TypeOf(d.str(t, "type", false))
			if err != nil {
				d.fail("%s: type: %v", where, err)
				continue
			}
			ans, ansShape, err := TypeOf(d.str(t, "answer", false))
			if err != nil {
				d.fail("%s: answer: %v", where, err)
				continue
			}
			h := d.str(t, "help", false)
			if kind == "requests" {
				c.addRequest(RequestDecl{Port: n, Req: req, Ans: ans, Help: h, ReqShape: reqShape, AnsShape: ansShape})
				continue
			}
			c.addVerb(&verb{decl: VerbDecl{Verb: n, Req: req, Ans: ans, Help: h, ReqShape: reqShape, AnsShape: ansShape}})
		}
	}
	for port := range c.requests {
		_, isIn := c.inputs[port]
		_, isOut := c.outputs[port]
		if isIn || isOut {
			c.fail("request port %s is also an input or an output", port)
		}
	}
	for port := range c.inputs {
		if _, taken := c.outputs[port]; taken {
			c.fail("port %s is both an input and an output", port)
		}
	}
	if len(c.verbs) > 0 && !c.io {
		c.fail("component %s accepts verbs but carries no I/O flag: only an I/O component reaches the outside", name)
	}
	c.errs = append(d.errs, c.errs...)
	if err := c.Err(); err != nil {
		return nil, err
	}
	return c, nil
}

var shapeName = regexp.MustCompile(`^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$`)

// TypeOf answers the Go type a declared type reads as, and the named JSON
// shape it carries where it is no plain type: int, float, string, bool, [T],
// or a shape such as github.issues, read as any.
func TypeOf(s string) (reflect.Type, string, error) {
	switch s {
	case "int":
		return reflect.TypeFor[int](), "", nil
	case "float":
		return reflect.TypeFor[float64](), "", nil
	case "string":
		return reflect.TypeFor[string](), "", nil
	case "bool":
		return reflect.TypeFor[bool](), "", nil
	}
	if inner, ok := strings.CutPrefix(s, "["); ok {
		if inner, ok := strings.CutSuffix(inner, "]"); ok {
			t, shape, err := TypeOf(inner)
			if err != nil {
				return nil, "", err
			}
			if shape != "" {
				shape = "[" + shape + "]"
			}
			return reflect.SliceOf(t), shape, nil
		}
	}
	if shapeName.MatchString(s) {
		return reflect.TypeFor[any](), s, nil
	}
	return nil, "", fmt.Errorf("%q is no type: int, float, string, bool, [T], or a named shape such as github.issues", s)
}

// decoder reads a declaration's tables and keeps what is wrong with them.
type decoder struct{ errs []string }

func (d *decoder) fail(format string, a ...any) { d.errs = append(d.errs, fmt.Sprintf(format, a...)) }

// keys refuses a key of t that is not one of allowed.
func (d *decoder) keys(t map[string]any, where string, allowed ...string) {
	for _, k := range sortedKeys(t) {
		ok := false
		for _, a := range allowed {
			ok = ok || a == k
		}
		if !ok {
			if where == "" {
				d.fail("no key %s: a declaration holds %s", k, strings.Join(allowed, ", "))
			} else {
				d.fail("%s: no key %s: it holds %s", where, k, strings.Join(allowed, ", "))
			}
		}
	}
}

func (d *decoder) table(doc map[string]any, key string) map[string]any {
	v, ok := doc[key]
	if !ok {
		return nil
	}
	t, ok := v.(map[string]any)
	if !ok {
		d.fail("%s is no table", key)
	}
	return t
}

func (d *decoder) sub(t map[string]any, key, where string, allowed ...string) map[string]any {
	s, ok := t[key].(map[string]any)
	if !ok {
		d.fail("%s is no table", where)
		return map[string]any{}
	}
	d.keys(s, where, allowed...)
	return s
}

func (d *decoder) str(t map[string]any, key string, required bool) string {
	v, ok := t[key]
	if !ok {
		if required {
			d.fail("no %s", key)
		}
		return ""
	}
	s, ok := v.(string)
	if !ok {
		d.fail("%s is no string", key)
	}
	return s
}

func (d *decoder) flag(t map[string]any, where, key string) bool {
	v, ok := t[key]
	if !ok {
		return false
	}
	b, ok := v.(bool)
	if !ok {
		d.fail("%s: %s is true or false", where, key)
	}
	return b
}

// port reads a declared port's type, built-in value and help.
func (d *decoder) port(t map[string]any, where, name string) (Port, bool) {
	typ, shape, err := TypeOf(d.str(t, "type", false))
	if err != nil {
		d.fail("%s: type: %v", where, err)
		return Port{}, false
	}
	raw, ok := t["builtin"]
	if !ok {
		d.fail("%s has no built-in value", where)
		return Port{}, false
	}
	builtin, err := builtinValue(raw, typ)
	if err != nil {
		d.fail("%s: builtin takes %s: %v", where, d.str(t, "type", false), err)
		return Port{}, false
	}
	return Port{Port: name, Type: typ, Builtin: builtin, Help: d.str(t, "help", false), Shape: shape}, true
}

// builtinValue converts a built-in value as TOML reads it into its port's type;
// a shape's reads as JSON would, so it equals what a commit of it reads.
func builtinValue(v any, t reflect.Type) (any, error) {
	if t.Kind() == reflect.Interface {
		data, err := json.Marshal(v)
		if err != nil {
			return nil, err
		}
		var out any
		return out, json.Unmarshal(data, &out)
	}
	return configValue(v, t)
}

// runRemote runs one command in the declared component's process, step by
// step: each step's writes and requests are read as the ports' types.
func (c *Component) runRemote(ctx context.Context, name string, read Reader, args []string, say func(string)) (Result, error) {
	r := c.decl.remote
	if r == nil {
		return Result{}, fmt.Errorf("component %s runs in its own process, and none has attached", c.name)
	}
	inputs := map[string]any{}
	for _, port := range c.commands[name].in.ports {
		inputs[port] = read(port)
	}
	call := fmt.Sprintf("%d", c.decl.calls.Add(1))
	if args == nil {
		args = []string{}
	}
	return c.step(ctx, name, Step{Call: call, Step: 1, Args: args, Inputs: inputs}, say)
}

func (c *Component) step(ctx context.Context, name string, s Step, say func(string)) (Result, error) {
	a, err := c.decl.remote.Command(ctx, name, s, say)
	if err != nil {
		return Result{}, err
	}
	if a.Error != "" {
		return Result{}, errors.New(a.Error)
	}
	// A refused answer that holds a continuation leaves it waiting in the
	// process: tell it the call is given up.
	refused := func(err error) (Result, error) {
		if a.Then {
			c.decl.remote.Stop(name, s.Call, err.Error())
		}
		return Result{}, err
	}
	res := Result{Text: a.Text, Lines: a.Lines, Said: say != nil}
	for _, w := range a.Writes {
		write := Write{Port: w.Port, Key: w.Key, Gone: w.Gone}
		if o, ok := c.outputs[w.Port]; ok && !w.Gone {
			v, err := decodeAs(w.Value, o.Type)
			if err != nil {
				return refused(fmt.Errorf("component %s: output %s takes %s, not %s", c.name, w.Port, o.Type, err))
			}
			write.Value = v
		}
		res.Writes = append(res.Writes, write)
	}
	for _, q := range a.Requests {
		ask := Ask{Port: q.Port}
		if rp, ok := c.requests[q.Port]; ok {
			v, err := decodeAs(q.Value, rp.Req)
			if err != nil {
				return refused(fmt.Errorf("component %s: request port %s sends %s, not %s", c.name, q.Port, rp.Req, err))
			}
			ask.Value = v
		}
		res.Requests = append(res.Requests, ask)
	}
	if a.Then {
		next, remote := s.Step+1, c.decl.remote
		res.Then = func(answers []any) (Result, error) {
			data, err := json.Marshal(answers)
			if err != nil {
				remote.Stop(name, s.Call, err.Error())
				return Result{}, err
			}
			return c.step(ctx, name, Step{Call: s.Call, Step: next, Answers: data}, say)
		}
		res.Stop = func(reason string) { remote.Stop(name, s.Call, reason) }
	}
	return res, nil
}

// serveRemote hands one request to the declared I/O component's process and
// reads its answer as the verb's answer type.
func (c *Component) serveRemote(ctx context.Context, v VerbDecl, req any) (any, error) {
	r := c.decl.remote
	if r == nil {
		return nil, fmt.Errorf("component %s runs in its own process, and none has attached", c.name)
	}
	data, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	ans, err := r.Serve(ctx, v.Verb, data)
	if err != nil {
		return nil, err
	}
	out, err := decodeAs(ans, v.Ans)
	if err != nil {
		return nil, fmt.Errorf("component %s: verb %s answers %s, not %s", c.name, v.Verb, v.Ans, err)
	}
	return out, nil
}

// decodeAs reads a JSON value as type t; its error names the JSON kind it met.
func decodeAs(data json.RawMessage, t reflect.Type) (any, error) {
	v := reflect.New(t)
	if len(data) == 0 {
		data = json.RawMessage("null")
	}
	if err := json.Unmarshal(data, v.Interface()); err != nil {
		return nil, errors.New(jsonKind(data))
	}
	return v.Elem().Interface(), nil
}

// jsonKind names what a JSON value is: a number, a string, a list, an object, true or false, or null.
func jsonKind(data json.RawMessage) string {
	var v any
	if json.Unmarshal(data, &v) != nil {
		return "JSON"
	}
	switch v.(type) {
	case float64:
		return "a number"
	case string:
		return "a string"
	case []any:
		return "a list"
	case map[string]any:
		return "an object"
	case bool:
		return "a bool"
	}
	return "null"
}

// Inputs answers an instance's inputs by local port, config among them, at
// the store's newest revision, and that revision: what in.<i> answers.
func (ix *Index) Inputs(instance string) (map[string]any, uint64, error) {
	in, ok := ix.insts[instance]
	if !ok {
		return nil, 0, fmt.Errorf("index: no instance %s", instance)
	}
	snap := ix.Snapshot()
	read := in.reader(snap, "")
	out := map[string]any{}
	for _, p := range in.comp.Inputs() {
		out[p.Port] = read(p.Port)
		if out[p.Port] == nil {
			out[p.Port] = p.Builtin
		}
	}
	return out, snap.Revision(), nil
}

// OnRun hands the index what tells a declared instance's process to run its
// derivations: after each commit that moves an input of one, fn gets its
// name and the revision, once per commit.
func (ix *Index) OnRun(fn func(instance string, revision uint64)) {
	ix.mu.Lock()
	defer ix.mu.Unlock()
	ix.onRun = fn
}

// sortedRuns answers the instances a commit's wave left to their processes, sorted.
func sortedRuns(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
