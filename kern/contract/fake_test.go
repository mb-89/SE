package contract

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/index"
	"github.com/mb-89/kern/kerntest"
)

// The suite's cases, in cases.json: each runs against the Go fake here, the
// Python fake (python/tests/test_kern_contract.py) and the real core (real_test.go).
type suite struct {
	Cases []contractCase `json:"cases"`
}

type contractCase struct {
	Name    string                     `json:"name"`
	Seed    map[string]json.RawMessage `json:"seed"`
	Config  map[string]json.RawMessage `json:"config"`
	Answers map[string][]answer        `json:"answers"`
	Derive  string                     `json:"derive"`
	Run     []string                   `json:"run"`
	Want    struct {
		Text     *string           `json:"text"`
		Lines    []string          `json:"lines"`
		Error    []string          `json:"error"`
		Requests []request         `json:"requests"`
		Outputs  map[string]output `json:"outputs"`
	} `json:"want"`
}

type answer struct {
	Answer json.RawMessage `json:"answer"`
	Error  string          `json:"error"`
}

type request struct {
	Port  string          `json:"port"`
	Value json.RawMessage `json:"value"`
}

type output struct {
	Value    json.RawMessage `json:"value"`
	Provided bool            `json:"provided"`
}

func cases(t *testing.T) []contractCase {
	t.Helper()
	var s suite
	readJSON(t, "cases.json", &s)
	if len(s.Cases) == 0 {
		t.Fatal("cases.json holds no case")
	}
	return s.Cases
}

func readJSON(t *testing.T, file string, v any) {
	t.Helper()
	data, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, v); err != nil {
		t.Fatalf("%s: %v", file, err)
	}
}

// sameJSON says whether a value marshals to the JSON want holds.
func sameJSON(t *testing.T, got any, want json.RawMessage) bool {
	t.Helper()
	var g, w any
	data, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	if json.Unmarshal(data, &g) != nil || json.Unmarshal(want, &w) != nil {
		t.Fatalf("no JSON: %s, %s", data, want)
	}
	return reflect.DeepEqual(g, w)
}

// judge holds what a leg answered to the case's want.
func (c contractCase) judge(t *testing.T, text string, lines []string, err error, asked []request, out func(port string) (any, bool)) {
	t.Helper()
	if c.Want.Text != nil && text != *c.Want.Text {
		t.Errorf("the text is %q, and wants %q", text, *c.Want.Text)
	}
	if c.Want.Lines != nil && !reflect.DeepEqual(append([]string{}, lines...), c.Want.Lines) {
		t.Errorf("the lines are %q, and want %q", lines, c.Want.Lines)
	}
	switch {
	case len(c.Want.Error) == 0 && err != nil:
		t.Errorf("it fails: %v", err)
	case len(c.Want.Error) > 0 && err == nil:
		t.Errorf("it passes, and wants an error holding %q", c.Want.Error)
	case err != nil:
		for _, s := range c.Want.Error {
			if !strings.Contains(err.Error(), s) {
				t.Errorf("the error %q holds no %q", err, s)
			}
		}
	}
	if c.Want.Requests != nil {
		if len(asked) != len(c.Want.Requests) {
			t.Errorf("it asked %d requests, and wants %d: %+v", len(asked), len(c.Want.Requests), asked)
		}
		for i := range min(len(asked), len(c.Want.Requests)) {
			w := c.Want.Requests[i]
			if asked[i].Port != w.Port || !sameJSON(t, asked[i].Value, w.Value) {
				t.Errorf("request %d is %s %s, and wants %s %s", i+1, asked[i].Port, asked[i].Value, w.Port, w.Value)
			}
		}
	}
	for port, w := range c.Want.Outputs {
		v, provided := out(port)
		if provided != w.Provided || !sameJSON(t, v, w.Value) {
			t.Errorf("output %s reads %v, provided %v, and wants %s, provided %v", port, v, provided, w.Value, w.Provided)
		}
	}
}

// The Go fake leg: tally in Go, as tally's component.toml declares it, run on kerntest.
func TestTheGoFakeKeepsTheContract(t *testing.T) {
	for _, c := range cases(t) {
		t.Run(c.Name, func(t *testing.T) {
			f, err := kerntest.New(goTally())
			if err != nil {
				t.Fatal(err)
			}
			ports := map[string]reflect.Type{}
			for _, p := range goTally().Inputs() {
				ports[p.Port] = p.Type
			}
			for port, raw := range c.Seed {
				if err := f.Seed(port, decode(t, raw, ports[port])); err != nil {
					t.Fatal(err)
				}
			}
			for key, raw := range c.Config {
				if err := f.Config(key, decode(t, raw, ports[index.ConfigPrefix+key])); err != nil {
					t.Fatal(err)
				}
			}
			for _, r := range goTally().Requests() {
				queue := c.Answers[r.Port]
				ans := r.Ans
				if err := f.Answer(r.Port, func(any) (any, error) {
					if len(queue) == 0 {
						return nil, errors.New("the case gives no more answers")
					}
					a := queue[0]
					queue = queue[1:]
					if a.Error != "" {
						return nil, errors.New(a.Error)
					}
					return decode(t, a.Answer, ans), nil
				}); err != nil {
					t.Fatal(err)
				}
			}
			var text string
			if c.Derive != "" {
				err = f.Derive(c.Derive)
			}
			if len(c.Run) > 0 {
				text, err = f.Call(c.Run[0], c.Run[1:]...)
			}
			var asked []request
			for _, a := range f.Requests() {
				data, _ := json.Marshal(a.Value)
				asked = append(asked, request{Port: a.Port, Value: data})
			}
			c.judge(t, text, f.Lines(), err, asked, func(port string) (any, bool) {
				v, err := f.Out(port)
				if err != nil {
					t.Fatal(err)
				}
				return v.V, v.Provided
			})
		})
	}
}

func decode(t *testing.T, raw json.RawMessage, typ reflect.Type) any {
	t.Helper()
	if typ == nil {
		t.Fatalf("the case names a port tally does not declare: %s", raw)
	}
	v := reflect.New(typ)
	if err := json.Unmarshal(raw, v.Interface()); err != nil {
		t.Fatal(err)
	}
	return v.Elem().Interface()
}

type tallyIn struct {
	Numbers []int `index:"numbers"`
	Scale   int   `index:"config/scale"`
}

// goTally is the fixture component tally in Go: the same declaration as
// fixture/tally/component.toml, answered as fixture/tally/__init__.py answers it.
func goTally() *index.Component {
	note := index.Output("note", "", "The last note taken.")
	post := index.Request[string, int]("post", "Appends a line to a ledger.")
	cmd := func(name, usage, summary, help string, session bool) index.CommandDecl {
		return index.CommandDecl{Name: name, Usage: usage, Summary: summary, Help: help, Group: "Fixtures", Session: session, Class: index.Batch}
	}
	return index.Declare("tally", "Sums numbers and takes notes.",
		index.Config("scale", 1, "What the sum is multiplied by."),
		index.Derived("total", 0, "The sum of the numbers, scaled.", func(in tallyIn) (int, error) {
			sum := 0
			for _, n := range in.Numbers {
				sum += n
			}
			return sum * in.Scale, nil
		}),
		note, post,
		index.Command(cmd("tally note", "tally note WORDS...", "Take a note.", "Keeps the words as the last note, and says how many numbers stand.", true),
			func(in tallyIn, args []string) (index.Result, error) {
				r := index.Result{Lines: []string{"Phase: noting"}}
				if len(args) == 0 {
					return r, errors.New("tally note takes the words to keep")
				}
				words := strings.Join(args, " ")
				r.Text = fmt.Sprintf("noted %q beside %d numbers", words, len(in.Numbers))
				r.Writes = []index.Write{note.Set(words)}
				return r, nil
			}),
		index.Command(cmd("tally file", "tally file WORDS...", "File each word as a line.", "Posts each word to the ledger in order; a refused post stops the rest.", false),
			func(_ tallyIn, args []string) (index.Result, error) {
				began := fmt.Sprintf("filing %d words", len(args))
				asks := make([]index.Ask, len(args))
				for i, a := range args {
					asks[i] = post.Ask(a)
				}
				return index.Result{Text: began, Writes: []index.Write{note.Set(began)}, Requests: asks,
					Then: func(answers []any) (index.Result, error) {
						if len(answers) == 0 {
							return index.Result{Text: "nothing filed"}, nil
						}
						entry := fmt.Sprintf("%s as line %d", args[len(args)-1], post.Answer(answers[len(answers)-1]))
						return index.Result{Text: "filed " + entry, Writes: []index.Write{note.Set(entry)}}, nil
					}}, nil
			}),
		index.Command(cmd("tally stray", "tally stray", "Write an output the component does not declare.", "The core refuses it.", false),
			func(tallyIn, []string) (index.Result, error) {
				return index.Result{Writes: []index.Write{{Port: "nowhere", Value: "x"}}}, nil
			}),
		index.Command(cmd("tally wrong", "tally wrong", "Write a number to the note.", "The core refuses it: the note is a string.", false),
			func(tallyIn, []string) (index.Result, error) {
				return index.Result{Writes: []index.Write{{Port: "note", Value: 7}}}, nil
			}),
	)
}

// The Go fixture and tally's component.toml declare one component: a drift
// between them would let the Go fake leg pass on another contract.
func TestTheGoFixtureMatchesItsDeclaration(t *testing.T) {
	declared, err := index.ReadDeclaration(filepath.Join("fixture", "tally", index.DeclarationFile))
	if err != nil {
		t.Fatal(err)
	}
	g := goTally()
	same := func(what string, a, b any) {
		t.Helper()
		if !reflect.DeepEqual(a, b) {
			t.Errorf("the %s differ: Go %+v, component.toml %+v", what, a, b)
		}
	}
	same("names", g.Name(), declared.Name())
	same("helps", g.Help(), declared.Help())
	same("inputs", g.Inputs(), declared.Inputs())
	same("outputs", g.Outputs(), declared.Outputs())
	same("config", g.Config(), declared.Config())
	same("commands", g.Commands(), declared.Commands())
	same("request ports", g.Requests(), declared.Requests())
	same("derivations", g.Derivations(), declared.Derivations())
}

// A name, a command name or a verb rides as the subject tokens subjects.json
// gives, and back; the Python peer is held to the same file.
func TestSubjectTokens(t *testing.T) {
	var v struct {
		Names []struct {
			Name, Subject string
		} `json:"names"`
		Tokens []struct {
			Word, Token string
		} `json:"tokens"`
	}
	readJSON(t, "subjects.json", &v)
	for _, n := range v.Names {
		if got := bus.Subject(n.Name); got != n.Subject {
			t.Errorf("%s rides as %s, and wants %s", n.Name, got, n.Subject)
		}
		if got := bus.Name(n.Subject); got != n.Name {
			t.Errorf("%s stands for %s, and wants %s", n.Subject, got, n.Name)
		}
	}
	for _, w := range v.Tokens {
		if got := bus.Token(w.Word); got != w.Token {
			t.Errorf("%q rides as %s, and wants %s", w.Word, got, w.Token)
		}
		if got := bus.Word(w.Token); got != w.Word {
			t.Errorf("%s stands for %q, and wants %q", w.Token, got, w.Word)
		}
	}
}

// Go's reader refuses what declarations.json refuses, as Python's does, and
// hashes a declaration's bytes with CRLF read as LF.
func TestDeclarationsAreRefusedAlike(t *testing.T) {
	var v struct {
		Refused []struct {
			Name, Text string
			Error      []string
		} `json:"refused"`
		Hash struct {
			Text   string `json:"text"`
			SameAs string `json:"same_as"`
		} `json:"hash"`
	}
	readJSON(t, "declarations.json", &v)
	for _, r := range v.Refused {
		_, err := index.ParseDeclaration([]byte(r.Text))
		if err == nil {
			t.Errorf("%s: the declaration is taken", r.Name)
			continue
		}
		for _, s := range r.Error {
			if !strings.Contains(err.Error(), s) {
				t.Errorf("%s: the refusal %q holds no %q", r.Name, err, s)
			}
		}
	}
	if a, b := index.Hash([]byte(v.Hash.Text)), index.Hash([]byte(v.Hash.SameAs)); a != b || !strings.HasPrefix(a, "sha256:") {
		t.Errorf("CRLF and LF hash as %s and %s", a, b)
	}
}
