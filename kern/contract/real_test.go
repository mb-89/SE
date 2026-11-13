package contract

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
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

// PythonEnv names the Python the real leg runs tally's process with; where
// unset, the first of python3 and python on the path that has tomllib (3.11+).
const PythonEnv = "KERN_PYTHON"

var python struct {
	once sync.Once
	path string
	err  error
}

func pythonPath(t *testing.T) string {
	t.Helper()
	python.once.Do(func() {
		candidates := []string{os.Getenv(PythonEnv)}
		if candidates[0] == "" {
			candidates = []string{"python3", "python"}
		}
		var tried []string
		for _, c := range candidates {
			p, err := exec.LookPath(c)
			if err != nil {
				tried = append(tried, c+": not on the path")
				continue
			}
			if out, err := exec.Command(p, "-c", "import tomllib").CombinedOutput(); err != nil {
				tried = append(tried, fmt.Sprintf("%s: no tomllib, so below 3.11: %s", p, strings.TrimSpace(string(out))))
				continue
			}
			python.path = p
			return
		}
		python.err = fmt.Errorf("the real leg runs tally's process in Python 3.11 or later, and finds none (%s); name one in %s", strings.Join(tried, "; "), PythonEnv)
	})
	if python.err != nil {
		t.Fatal(python.err)
	}
	return python.path
}

// sdk is kern's Python SDK, which tally's process imports.
func sdk(t *testing.T) string {
	t.Helper()
	p, err := filepath.Abs(filepath.Join("..", "python"))
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// core is a running kern with tally placed in its own Python process, and
// the case's peers: the source it seeds as, the ledger it answers as, a client.
type core struct {
	root   string
	s      host.Standing
	client *nats.Conn
	source *nats.Conn
	ledger *nats.Conn

	mu    sync.Mutex
	asked []request
}

// startCore writes a checkout with the three fixture components and a wiring
// that places tally, starts kern there and attaches the case's peers.
func startCore(t *testing.T, config map[string]json.RawMessage, attach bool) *core {
	t.Helper()
	root := checkout(t)
	for _, comp := range []string{"tally", "source", "ledger"} {
		dir := filepath.Join(root, "components", comp)
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
		for _, f := range []string{index.DeclarationFile, "__init__.py"} {
			data, err := os.ReadFile(filepath.Join("fixture", comp, f))
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(dir, f), data, 0o600); err != nil {
				t.Fatal(err)
			}
		}
	}
	cfg := ""
	for k, v := range config {
		cfg += fmt.Sprintf("config = { %s = %s }\n", k, v)
	}
	command, _ := json.Marshal([]string{pythonPath(t), "-m", "kern", "run", "components/tally"})
	wiring := fmt.Sprintf(`[instances.source]
component = "source"

[instances.tally]
component = "tally"
command = %s
%s
[instances.ledger]
component = "ledger"

[wires]
"tally.numbers" = "source.numbers"
"tally.post" = "ledger.append"
`, command, cfg)
	if err := os.WriteFile(filepath.Join(root, index.WiringFile), []byte(wiring), 0o600); err != nil {
		t.Fatal(err)
	}
	env := []string{"PYTHONPATH=" + sdk(t), "PYTHONDONTWRITEBYTECODE=1"}
	want(t, run(t, env, "start", "--root", root), 0, "kern: started")
	want(t, run(t, nil, "status", "--root", root, "--wait", wait), 0, "kern: running")
	c := &core{root: root, s: standing(t, root)}
	c.client = c.dial(t, bus.Client)
	c.source = c.dial(t, "source")
	c.ledger = c.dial(t, "ledger")
	if attach {
		for inst, nc := range map[string]*nats.Conn{"source": c.source, "ledger": c.ledger} {
			if a := c.attach(t, nc, inst, ""); !a.Accepted {
				t.Fatalf("%s's attach is refused: %s", inst, a.Refused)
			}
		}
	}
	return c
}

func (c *core) dial(t *testing.T, user string) *nats.Conn {
	t.Helper()
	nc, err := bus.Dial(c.s.Bus, user, c.s.Users[user])
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(nc.Close)
	return nc
}

// attach commits an instance's attach, with its declaration's hash where hash is "".
func (c *core) attach(t *testing.T, nc *nats.Conn, inst, hash string) host.CommitAnswer {
	t.Helper()
	if hash == "" {
		data, err := os.ReadFile(filepath.Join(c.root, "components", inst, index.DeclarationFile))
		if err != nil {
			t.Fatal(err)
		}
		hash = index.Hash(data)
	}
	return c.commit(t, nc, inst, map[string]any{"attach": host.Attach{Contract: host.Contract, Hash: hash}})
}

func (c *core) commit(t *testing.T, nc *nats.Conn, inst string, body any) host.CommitAnswer {
	t.Helper()
	data, _ := json.Marshal(body)
	m, err := nc.Request(bus.Commit+bus.Subject(inst), data, 10*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var a host.CommitAnswer
	if err := json.Unmarshal(m.Data, &a); err != nil {
		t.Fatal(err)
	}
	return a
}

// answerAs answers the ledger's verb as the case says, and records each request in order.
func (c *core) answerAs(t *testing.T, answers []answer) {
	t.Helper()
	var mu sync.Mutex
	_, err := c.ledger.Subscribe(bus.IOVerb+"ledger."+bus.Token("append"), func(m *nats.Msg) {
		var body struct {
			Request json.RawMessage `json:"request"`
		}
		_ = json.Unmarshal(m.Data, &body)
		mu.Lock()
		defer mu.Unlock()
		reply := map[string]any{"error": "the case gives no more answers"}
		if len(answers) > 0 {
			a := answers[0]
			answers = answers[1:]
			if a.Error != "" {
				reply = map[string]any{"error": a.Error}
			} else {
				reply = map[string]any{"answer": a.Answer}
				c.mu.Lock()
				c.asked = append(c.asked, request{Port: "post", Value: body.Request})
				c.mu.Unlock()
			}
		}
		data, _ := json.Marshal(reply)
		_ = m.Respond(data)
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := c.ledger.Flush(); err != nil {
		t.Fatal(err)
	}
}

func (c *core) get(t *testing.T, name string) host.NameValue {
	t.Helper()
	m, err := c.client.Request(bus.Get+bus.Subject(name), nil, 10*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	var v host.NameValue
	if err := json.Unmarshal(m.Data, &v); err != nil {
		t.Fatal(err)
	}
	return v
}

// The real leg: each case against kern's binary, with tally's Python process
// placed by the core and attached over the bus.
func TestTheRealCoreKeepsTheContract(t *testing.T) {
	t.Parallel()
	for _, cs := range cases(t) {
		t.Run(cs.Name, func(t *testing.T) {
			t.Parallel()
			c := startCore(t, cs.Config, true)
			c.answerAs(t, cs.Answers["post"])
			var pushed chan json.RawMessage
			if cs.Derive != "" {
				pushed = make(chan json.RawMessage, 16)
				if _, err := c.client.Subscribe(bus.Val+bus.Subject("tally/"+cs.Derive), func(m *nats.Msg) {
					var v struct {
						Value json.RawMessage `json:"value"`
					}
					_ = json.Unmarshal(m.Data, &v)
					pushed <- v.Value
				}); err != nil {
					t.Fatal(err)
				}
				if err := c.client.Flush(); err != nil {
					t.Fatal(err)
				}
			}
			if raw, ok := cs.Seed["numbers"]; ok {
				a := c.commit(t, c.source, "source", map[string]any{"writes": []map[string]any{{"port": "numbers", "value": raw}}})
				if !a.Accepted {
					t.Fatalf("the seed is refused: %s", a.Refused)
				}
			}
			var text string
			var lines []string
			var err error
			if cs.Derive != "" {
				// The derivation runs in tally's process, on its attach and on each seed: wait for its value.
				wantValue := cs.Want.Outputs[cs.Derive].Value
				deadline := time.After(20 * time.Second)
			waiting:
				for {
					select {
					case v := <-pushed:
						if sameJSON(t, v, wantValue) {
							break waiting
						}
					case <-deadline:
						t.Fatalf("tally's %s is never pushed as %s", cs.Derive, wantValue)
					}
				}
			}
			if len(cs.Run) > 0 {
				body, _ := json.Marshal(map[string][]string{"args": cs.Run[1:]})
				m, rerr := c.client.Request(bus.Call+bus.Token(cs.Run[0]), body, 30*time.Second)
				if rerr != nil {
					t.Fatal(rerr)
				}
				var a host.CallAnswer
				if err := json.Unmarshal(m.Data, &a); err != nil {
					t.Fatal(err)
				}
				text, lines = a.Text, a.Lines
				if a.Error != "" {
					err = errors.New(a.Error)
				}
			}
			c.mu.Lock()
			asked := append([]request{}, c.asked...)
			c.mu.Unlock()
			cs.judge(t, text, lines, err, asked, func(port string) (any, bool) {
				v := c.get(t, "tally/"+port)
				if v.Error != "" {
					t.Fatalf("get tally/%s: %s", port, v.Error)
				}
				return v.Value, v.Provided
			})
		})
	}
}

// The core takes an attach only with the contract it speaks and the
// declaration it read at its start, and refuses a declared instance's writes before it.
func TestTheRealCoreRefusesAForeignAttach(t *testing.T) {
	t.Parallel()
	c := startCore(t, nil, false)
	seed := map[string]any{"writes": []map[string]any{{"port": "numbers", "value": []int{1}}}}
	if a := c.commit(t, c.source, "source", seed); a.Accepted || !strings.Contains(a.Refused, "instance source has not attached") {
		t.Fatalf("a commit before the attach answers %+v, and wants a refusal", a)
	}
	if a := c.attach(t, c.source, "source", "sha256:0"); a.Accepted || !strings.Contains(a.Refused, "declaration hash sha256:0") {
		t.Fatalf("an attach with another hash answers %+v, and wants a refusal naming the hash", a)
	}
	a := c.commit(t, c.source, "source", map[string]any{"attach": host.Attach{Contract: 2, Hash: "x"}})
	if a.Accepted || !strings.Contains(a.Refused, "contract 2, and this core speaks contract 1") {
		t.Fatalf("an attach with contract 2 answers %+v, and wants a refusal naming both contracts", a)
	}
	if a := c.attach(t, c.source, "source", ""); !a.Accepted {
		t.Fatalf("the attach with the declaration's hash answers %+v", a)
	}
	if a := c.commit(t, c.source, "source", seed); !a.Accepted {
		t.Fatalf("a commit after the attach answers %+v", a)
	}
	// tally's own process attached: the health names it once its first call answers.
	m, err := c.client.Request(bus.Call+bus.Token("tally note"), []byte(`{"args":["up"]}`), 30*time.Second)
	if err != nil || !strings.Contains(string(m.Data), "noted") {
		t.Fatalf("tally note answers %v, %v", m, err)
	}
	h, err := c.client.Request(host.HealthSubject, nil, 10*time.Second)
	if err != nil || !strings.Contains(string(h.Data), `"attached":["source","tally"]`) {
		t.Fatalf("the health answers %v, %v, and wants source and tally attached", h, err)
	}
}
