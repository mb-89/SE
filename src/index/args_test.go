package index_test

import (
	"errors"
	"flag"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/index/indextest"
)

// shown is a command that declares a flag, an issue number and a reply that
// is data: its own code reads the parsed values and answers text and data.
var shown = index.Declare("shower", "Shows an issue.",
	index.Command(index.CommandDecl{
		Name: "show", Usage: "show N [--times K] [--json]", Summary: "Show issue N.", Help: "Shows issue N K times.",
		Group: "Fixtures", Class: index.Interactive, Words: index.Number, JSON: true,
		Flags: []index.Flag{{Name: "times", Default: 1, Help: "show it `K` times"}},
	}, func(_ struct{}, a index.Args) (index.Result, error) {
		n, k := a.Number, a.Int("times")
		return index.Result{
			Text: strings.TrimSpace(strings.Repeat(fmt.Sprintf("#%d ", n), k)),
			Data: map[string]int{"issue": n, "times": k},
		}, nil
	}))

// The collector parses a declared flag and a declared issue number, and
// renders a declared reply as text, or as JSON where the call says --json.
func TestTheCollectorParsesAndRendersADeclaredCommand(t *testing.T) {
	t.Parallel()
	f, err := indextest.New(shown)
	must(t, err)
	for _, c := range []struct {
		args []string
		want string
	}{
		{[]string{"7"}, "#7"},
		{[]string{"#7", "--times", "2"}, "#7 #7"},
		{[]string{"--times=2", "7"}, "#7 #7"},
		{[]string{"7", "--json"}, `{"issue":7,"times":1}`},
		{[]string{"--json", "--times", "3", "#7"}, `{"issue":7,"times":3}`},
	} {
		if got, err := f.Call("show", c.args...); err != nil || got != c.want {
			t.Errorf("show %v answers %q, %v; want %q", c.args, got, err, c.want)
		}
	}
	for _, c := range []struct {
		args []string
		want string
	}{
		{nil, `show takes one issue number, not ""`},
		{[]string{"7", "8"}, `show takes one issue number, not "7 8"`},
		{[]string{"seven"}, `show takes one issue number, not "seven"`},
		{[]string{"7", "--times", "x"}, `invalid value "x" for flag -times`},
		{[]string{"7", "--color"}, "flag provided but not defined: -color"},
	} {
		if _, err := f.Call("show", c.args...); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("show %v fails with %v, want %q", c.args, err, c.want)
		}
	}
	if _, err := f.Call("show", "--help"); !errors.Is(err, flag.ErrHelp) {
		t.Errorf("show --help fails with %v, want flag.ErrHelp", err)
	}
}

// Every kind of flag and of words parses as declared, a Pick taking its
// number from the word after it; a command takes no word it does not declare.
func TestTheCollectorParsesEveryKind(t *testing.T) {
	t.Parallel()
	d := index.CommandDecl{Name: "pull", Flags: []index.Flag{
		{Name: "take", Default: index.Pick{}, Help: "take it"},
		{Name: "for", Default: 8 * time.Minute, Help: "this long"},
		{Name: "title", Default: "", Help: "a title"},
		{Name: "full", Default: false, Help: "all of it"},
	}}
	a, err := d.Parse([]string{"--take", "#5", "--for", "1m", "--title", "T", "--full"})
	must(t, err)
	if a.Pick("take") != (index.Pick{Set: true, N: 5}) || a.Duration("for") != time.Minute || a.String("title") != "T" || !a.Bool("full") || !a.Given("title") {
		t.Fatalf("parsed %+v", a)
	}
	if a, err = d.Parse(nil); err != nil || a.Pick("take").Set || a.Duration("for") != 8*time.Minute || a.Given("title") {
		t.Fatalf("parsed nothing as %+v, %v", a, err)
	}
	if a, err = d.Parse([]string{"--take=3"}); err != nil || a.Pick("take") != (index.Pick{Set: true, N: 3}) {
		t.Fatalf("parsed --take=3 as %+v, %v", a, err)
	}
	for _, words := range [][]string{{"5"}, {"--take", "5", "6"}, {"--take", "x"}} {
		if _, err := d.Parse(words); err == nil || !strings.Contains(err.Error(), "pull takes one issue number, after --take") {
			t.Errorf("pull %v fails with %v", words, err)
		}
	}
	if _, err := (index.CommandDecl{Name: "on"}).Parse([]string{"x"}); err == nil || err.Error() != `on takes no word "x"` {
		t.Errorf("on x fails with %v", err)
	}
	tree := index.CommandDecl{Name: "tree", Words: index.MaybeNumber}
	if a, err := tree.Parse(nil); err != nil || a.Number != 0 {
		t.Errorf("tree parsed as %+v, %v", a, err)
	}
	if _, err := tree.Parse([]string{"1", "2"}); err == nil || err.Error() != `tree takes at most one issue number, not "1 2"` {
		t.Errorf("tree 1 2 fails with %v", err)
	}
	help := index.CommandDecl{Name: "help", Words: index.AnyWords}
	if a, err := help.Parse([]string{"issue", "pull"}); err != nil || strings.Join(a.Words, " ") != "issue pull" {
		t.Errorf("help issue pull parsed as %+v, %v", a, err)
	}
}

// A flag without help, of a type the collector does not parse, or declared
// twice, is a broken declaration, refused at the start.
func TestTheCollectorRefusesABrokenFlag(t *testing.T) {
	t.Parallel()
	for _, c := range []struct {
		flags []index.Flag
		json  bool
		want  string
	}{
		{[]index.Flag{{Name: "x", Default: ""}}, false, "flag --x has no help"},
		{[]index.Flag{{Name: "x", Default: 1.5, Help: "x"}}, false, "flag --x is a float64"},
		{[]index.Flag{{Name: "x", Default: "", Help: "x"}, {Name: "x", Default: "", Help: "x"}}, false, "flag --x is declared twice"},
		{[]index.Flag{{Name: "json", Default: false, Help: "x"}}, true, "flag --json is declared twice"},
		{[]index.Flag{{Name: "body file", Default: "", Help: "x"}}, false, "is no name"},
	} {
		m := index.Declare("broken", "Broken.", index.Command(index.CommandDecl{
			Name: "b", Usage: "b", Summary: "B.", Help: "B.", Group: "Fixtures", Class: index.Batch, Flags: c.flags, JSON: c.json,
		}, func(struct{}, index.Args) (index.Result, error) { return index.Result{}, nil }))
		if err := m.Err(); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("flags %+v are refused with %v, want %q", c.flags, err, c.want)
		}
	}
}
