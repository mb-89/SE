package host

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/index"
	"github.com/nats-io/nats.go"
)

// The waits of the core on a declared component's process.
const (
	// AttachWait is how long a call to a command of a declared instance waits
	// for its process to attach, as one the core just placed does in milliseconds.
	AttachWait = 10 * time.Second
	// StepWait is how long the core waits for one request on a verb from a
	// declared component's process, and for word from one step of a command:
	// a step that says a line or beats on say.<i> waits StepWait again, so a
	// long step runs as long as its process lives.
	StepWait = 60 * time.Second
	// CallBeat is how often the core beats on a streaming call's progress
	// subject while the call runs, and a declared process on say.<i> while
	// its step runs (the Python SDK's runner).
	CallBeat = 5 * time.Second
)

// DeclarationDirs are where, under the checkout, the core finds the
// component.toml of a component no binary carries: components/<name>/ for one
// the application keeps, .se/components/<name>/ for an ad hoc one.
var DeclarationDirs = []string{"components", filepath.Join(".se", "components")}

// declarations reads the component.toml of every component the wiring names
// and no Go component answers, and refuses two instances of one: each
// instance of a declared component is one process.
func declarations(root string, w index.Wiring, compiled []*index.Component) ([]*index.Component, error) {
	have := map[string]bool{}
	for _, c := range compiled {
		have[c.Name()] = true
	}
	read := map[string]int{}
	var out []*index.Component
	for _, in := range w.Instances {
		if have[in.Component] {
			continue
		}
		if line, twice := read[in.Component]; twice {
			return nil, fmt.Errorf("kern serve: wiring line %d: instance %s: component %s is declared by its component.toml, and instance on line %d already runs it: one instance per declared component", in.Line, in.Name, in.Component, line)
		}
		var path string
		for _, dir := range DeclarationDirs {
			p := filepath.Join(root, dir, filepath.FromSlash(in.Component), index.DeclarationFile)
			if _, err := os.Stat(p); err == nil {
				path = p
				break
			}
		}
		if path == "" {
			continue // the catalog check names the missing component
		}
		c, err := index.ReadDeclaration(path)
		if err != nil {
			return nil, fmt.Errorf("kern serve: wiring line %d: instance %s: %w", in.Line, in.Name, err)
		}
		if c.Name() != in.Component {
			return nil, fmt.Errorf("kern serve: wiring line %d: instance %s: %s declares the component %s, not %s", in.Line, in.Name, path, c.Name(), in.Component)
		}
		read[in.Component] = in.Line
		out = append(out, c)
	}
	return out, nil
}

// remote is a declared instance's process, as the index reaches it over the bus.
type remote struct {
	c    *Core
	inst string
}

func (r remote) Command(name string, s index.Step, say func(string)) (index.Answer, error) {
	var a index.Answer
	if err := r.c.waitAttached(r.inst); err != nil {
		return a, err
	}
	data, _ := json.Marshal(s)
	// The step's answer and its process's say.<i> ride one channel, so the
	// lines said before the answer are read before it, in their order.
	heard := make(chan *nats.Msg, 64)
	inbox := r.c.nc.NewRespInbox()
	said := bus.Say + bus.Subject(r.inst)
	for _, subj := range []string{inbox, said} {
		sub, err := r.c.nc.ChanSubscribe(subj, heard)
		if err != nil {
			return a, fmt.Errorf("instance %s: command %q, step %d: %w", r.inst, name, s.Step, err)
		}
		defer func() { _ = sub.Unsubscribe() }()
	}
	if err := r.c.nc.PublishRequest(bus.Cmd+bus.Subject(r.inst)+"."+bus.Token(name), inbox, data); err != nil {
		return a, fmt.Errorf("instance %s: command %q, step %d: %w", r.inst, name, s.Step, err)
	}
	wait := r.c.o.StepWait
	quiet := time.NewTimer(wait)
	defer quiet.Stop()
	var live []string
	for {
		select {
		case m := <-heard:
			if m.Subject == said {
				var w struct {
					Call string  `json:"call"`
					Line *string `json:"line"`
				}
				if json.Unmarshal(m.Data, &w) != nil || w.Call != s.Call {
					continue // another call's word
				}
				if !quiet.Stop() {
					<-quiet.C
				}
				quiet.Reset(wait)
				if w.Line != nil {
					live = append(live, *w.Line)
					if say != nil {
						say(*w.Line)
					}
				}
				continue
			}
			if err := json.Unmarshal(m.Data, &a); err != nil {
				return a, fmt.Errorf("instance %s: command %q answers no result: %v", r.inst, name, err)
			}
			if say != nil {
				for _, l := range a.Lines {
					say(l)
				}
			}
			a.Lines = append(live, a.Lines...)
			return a, nil
		case <-quiet.C:
			return a, fmt.Errorf("instance %s: command %q, step %d: no answer, line or beat within %v", r.inst, name, s.Step, wait)
		case <-r.c.done:
			return a, fmt.Errorf("instance %s: command %q, step %d: the core ends", r.inst, name, s.Step)
		}
	}
}

func (r remote) Serve(verb string, req json.RawMessage) (json.RawMessage, error) {
	if err := r.c.waitAttached(r.inst); err != nil {
		return nil, err
	}
	data, _ := json.Marshal(map[string]json.RawMessage{"request": req})
	m, err := r.c.nc.Request(bus.IOVerb+bus.Subject(r.inst)+"."+bus.Token(verb), data, r.c.o.StepWait)
	if err != nil {
		return nil, fmt.Errorf("instance %s: verb %s: %w", r.inst, verb, err)
	}
	var a struct {
		Answer json.RawMessage `json:"answer"`
		Error  string          `json:"error"`
	}
	if err := json.Unmarshal(m.Data, &a); err != nil {
		return nil, fmt.Errorf("instance %s: verb %s answers no JSON: %v", r.inst, verb, err)
	}
	if a.Error != "" {
		return nil, errors.New(a.Error)
	}
	return a.Answer, nil
}

// Attach is what a declared instance's process commits first, on commit.<i>:
// the contract it speaks and its declaration's hash.
type Attach struct {
	Contract int    `json:"contract"`
	Hash     string `json:"hash"`
}

// attach takes a declared instance's attach, and refuses another contract or
// another declaration than the one the core read at its start.
func (c *Core) attach(inst string, a Attach) error {
	comp := c.declared[inst]
	switch {
	case comp == nil:
		return fmt.Errorf("instance %s is compiled in: only a declared component's process attaches", inst)
	case a.Contract != Contract:
		return fmt.Errorf("instance %s attaches with contract %d, and this core speaks contract %d", inst, a.Contract, Contract)
	case a.Hash != comp.DeclarationHash():
		return fmt.Errorf("instance %s attaches with the declaration hash %s, and the core read %s at its start: restart the core with the declaration the process runs", inst, a.Hash, comp.DeclarationHash())
	}
	c.mu.Lock()
	ch := c.attached[inst]
	select {
	case <-ch:
	default:
		close(ch)
	}
	c.mu.Unlock()
	if len(comp.Derivations()) > 0 {
		c.runInstance(inst, c.ix.Snapshot().Revision())
	}
	return nil
}

func (c *Core) isAttached(inst string) bool {
	c.mu.Lock()
	ch, ok := c.attached[inst]
	c.mu.Unlock()
	if !ok {
		return false
	}
	select {
	case <-ch:
		return true
	default:
		return false
	}
}

// waitAttached waits for a declared instance's process to attach, up to AttachWait.
func (c *Core) waitAttached(inst string) error {
	c.mu.Lock()
	ch, ok := c.attached[inst]
	c.mu.Unlock()
	if !ok {
		return fmt.Errorf("no declared instance %s", inst)
	}
	select {
	case <-ch:
		return nil
	case <-c.done:
		return errors.New("the core ends")
	case <-c.o.Clock.After(AttachWait):
		return fmt.Errorf("instance %s has not attached within %v", inst, AttachWait)
	}
}

// runInstance tells a declared instance's process that an input moved: run.<i>.
func (c *Core) runInstance(inst string, rev uint64) {
	if !c.isAttached(inst) {
		return // its attach runs it
	}
	data, _ := json.Marshal(map[string]uint64{"revision": rev})
	_ = c.nc.Publish(bus.Run+bus.Subject(inst), data)
}

// inputs answers in.<i>: the instance's inputs by local port at the newest revision.
func (c *Core) inputs(m *nats.Msg) {
	inst := bus.Name(strings.TrimPrefix(m.Subject, bus.In))
	in, rev, err := c.ix.Inputs(inst)
	if err != nil {
		c.reply(m, map[string]string{"error": err.Error()})
		return
	}
	c.reply(m, map[string]any{"revision": rev, "inputs": in})
}

// CallAnswer is what call.<command> answers: the progress lines, the text of
// every step, or why the command failed.
type CallAnswer struct {
	Text  string   `json:"text"`
	Lines []string `json:"lines"`
	Error string   `json:"error,omitempty"`
}

// Progress is what the core publishes on a call's progress subject while the
// call runs: each line as a step says it, or a beat every CallBeat, so the
// caller waits as long as the call lives instead of a fixed time.
type Progress struct {
	Line string `json:"line,omitempty"`
	Beat bool   `json:"beat,omitempty"`
}

// call answers call.<command>: it runs the command with the arguments the
// body names, {"args": [...], "progress"?: <subject>}, and answers its lines
// and text. Where the body names a progress subject, one in the caller's own
// inbox, the core streams each line there as it is said, and beats there
// while the call runs (docs/go-core.md "Progress and long calls").
func (c *Core) call(m *nats.Msg) {
	if m.Subject == StopSubject {
		return
	}
	c.event()
	name := bus.Word(strings.TrimPrefix(m.Subject, bus.Call))
	var body struct {
		Args     []string `json:"args"`
		Progress string   `json:"progress"`
	}
	if len(m.Data) > 0 {
		if err := json.Unmarshal(m.Data, &body); err != nil {
			c.reply(m, CallAnswer{Lines: []string{}, Error: fmt.Sprintf("call.%s: the body is no JSON of args: %v", bus.Token(name), err)})
			return
		}
	}
	if body.Progress != "" && !sameInbox(m.Reply, body.Progress) {
		c.reply(m, CallAnswer{Lines: []string{}, Error: fmt.Sprintf("call.%s: the progress subject %q lies outside the caller's inbox, the one its reply %q names", bus.Token(name), body.Progress, m.Reply)})
		return
	}
	go func() {
		var say func(string)
		stop := make(chan struct{})
		if body.Progress != "" {
			say = func(line string) { c.progress(body.Progress, Progress{Line: line}) }
			go func() {
				t := time.NewTicker(c.o.CallBeat)
				defer t.Stop()
				for {
					select {
					case <-stop:
						return
					case <-c.done:
						return
					case <-t.C:
						c.progress(body.Progress, Progress{Beat: true})
					}
				}
			}()
		}
		r, err := c.ix.CallSaying(name, say, body.Args...)
		close(stop)
		a := CallAnswer{Text: r.Text, Lines: append([]string{}, r.Lines...)}
		if err != nil {
			a.Error = err.Error()
		}
		c.reply(m, a)
	}()
}

func (c *Core) progress(subject string, p Progress) {
	data, _ := json.Marshal(p)
	_ = c.nc.Publish(subject, data)
}

// sameInbox says whether subject lies in the inbox the reply subject names:
// both under its first two tokens, _INBOX.<user in hex>, so a caller streams
// only to itself.
func sameInbox(reply, subject string) bool {
	parts := strings.SplitN(reply, ".", 3)
	if len(parts) < 3 || parts[0] != "_INBOX" {
		return false
	}
	prefix := parts[0] + "." + parts[1] + "."
	return strings.HasPrefix(subject, prefix) && len(subject) > len(prefix) && !strings.ContainsAny(subject, "*> ")
}
