package index

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"reflect"
	"strconv"
	"strings"
	"time"
)

// A command's boilerplate is the collector's, not the command's: a command
// declares its flags with their types, the words it takes beside them and
// whether its reply is data, and the collector parses a call by that
// declaration and renders the reply. The command's own code receives the
// parsed Args and answers its text and data.

// Flag is one flag a command takes.
type Flag struct {
	// Name is the flag's name, without its dashes: "body-file".
	Name string
	// Default is its value where a call does not give it, and its type is
	// the flag's: string, bool, int, time.Duration or Pick.
	Default any
	// Help is its one help line; a word in backquotes names its value, as
	// "a file `PATH` holding the body" gives --body-file PATH.
	Help string
}

// Pick is a flag that stands alone or names one issue number: --take,
// --take=N, or --take N, the number in the next word.
type Pick struct {
	// Set is whether the call gave the flag.
	Set bool
	// N is the issue number it named, 0 where it named none.
	N int
}

// Words says what a command takes beside its flags.
type Words string

const (
	// NoWords is a command that takes its flags alone.
	NoWords Words = ""
	// Number is a command that takes one issue number, N or #N, before,
	// between or after its flags.
	Number Words = "number"
	// MaybeNumber is a command that takes at most one issue number.
	MaybeNumber Words = "number?"
	// AnyWords is a command that takes any words, handed over as they stand.
	AnyWords Words = "words"
)

// Args is a call parsed as its command declares it: each flag's value, and
// the issue number or the words it took.
type Args struct {
	command string
	values  map[string]any
	given   map[string]bool
	// Number is the issue number a Number or MaybeNumber command took; 0 where none.
	Number int
	// Words are the words an AnyWords command took.
	Words []string
	// JSON is set where a command whose reply is data was called with --json.
	JSON bool
}

// String answers the value of the string flag name.
func (a Args) String(name string) string { return value[string](a, name) }

// Bool answers the value of the bool flag name.
func (a Args) Bool(name string) bool { return value[bool](a, name) }

// Int answers the value of the int flag name.
func (a Args) Int(name string) int { return value[int](a, name) }

// Duration answers the value of the duration flag name.
func (a Args) Duration(name string) time.Duration { return value[time.Duration](a, name) }

// Pick answers the value of the Pick flag name.
func (a Args) Pick(name string) Pick { return value[Pick](a, name) }

// Given says whether the call gave the flag name, even at its default.
func (a Args) Given(name string) bool { return a.given[name] }

// value answers flag name's value; a flag the command does not declare, or
// reads as another type, is a broken command, which its tests catch.
func value[T any](a Args, name string) T {
	v, ok := a.values[name].(T)
	if !ok {
		panic(fmt.Sprintf("index: command %q declares no %T flag --%s", a.command, v, name))
	}
	return v
}

// Render is the reply as the call asked for it: the data as JSON where it
// said --json, else the text.
func (a Args) Render(text string, data any) (string, error) {
	if !a.JSON {
		return text, nil
	}
	out, err := json.Marshal(data)
	return string(out), err
}

// jsonFlag is the flag a command whose reply is data takes.
var jsonFlag = Flag{Name: "json", Default: false, Help: "answer JSON"}

// flags are the flags d takes: those it declares, and --json where its reply is data.
func (d CommandDecl) flags() []Flag {
	if !d.JSON {
		return d.Flags
	}
	return append(d.Flags[:len(d.Flags):len(d.Flags)], jsonFlag)
}

// FlagSet is a flag set that takes the flags d takes, each at its default,
// which a help lists.
func (d CommandDecl) FlagSet() *flag.FlagSet {
	fs, _ := d.flagSet()
	return fs
}

// flagSet makes the flag set of d, and the values its flags parse into.
func (d CommandDecl) flagSet() (*flag.FlagSet, map[string]flag.Getter) {
	fs := flag.NewFlagSet(d.Name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	for _, f := range d.flags() {
		switch def := f.Default.(type) {
		case string:
			fs.String(f.Name, def, f.Help)
		case bool:
			fs.Bool(f.Name, def, f.Help)
		case int:
			fs.Int(f.Name, def, f.Help)
		case time.Duration:
			fs.Duration(f.Name, def, f.Help)
		case Pick:
			fs.Var(&pickValue{name: f.Name, v: def}, f.Name, f.Help)
		}
	}
	values := map[string]flag.Getter{}
	fs.VisitAll(func(f *flag.Flag) { values[f.Name] = f.Value.(flag.Getter) })
	return fs, values
}

// Parse reads the words of a call as d declares them. --help or -h answers
// flag.ErrHelp, for the adapter to answer the command's help.
func (d CommandDecl) Parse(words []string) (Args, error) {
	fs, values := d.flagSet()
	var taken []string
	for rest := words; ; {
		if err := fs.Parse(rest); err != nil {
			return Args{}, err
		}
		if fs.NArg() == 0 {
			break
		}
		word := fs.Arg(0)
		rest = fs.Args()[1:]
		if p := pending(values); p != nil {
			// --take N: the word after a Pick that named no number is its number.
			if p.v.N = issueNumber(word); p.v.N <= 0 {
				return Args{}, fmt.Errorf("%s takes one issue number, after --%s, not %q", d.Name, p.name, word)
			}
			continue
		}
		if d.Words == NoWords {
			if p := d.pickName(); p != "" {
				return Args{}, fmt.Errorf("%s takes one issue number, after --%s, not %q", d.Name, p, word)
			}
			return Args{}, fmt.Errorf("%s takes no word %q", d.Name, word)
		}
		taken = append(taken, word)
	}
	a := Args{command: d.Name, values: map[string]any{}, given: map[string]bool{}}
	for name, v := range values {
		a.values[name] = v.Get()
	}
	fs.Visit(func(f *flag.Flag) { a.given[f.Name] = true })
	a.JSON = d.JSON && a.Bool(jsonFlag.Name)
	switch d.Words {
	case Number:
		if len(taken) == 1 {
			a.Number = issueNumber(taken[0])
		}
		if a.Number <= 0 {
			return Args{}, fmt.Errorf("%s takes one issue number, not %q", d.Name, strings.Join(taken, " "))
		}
	case MaybeNumber:
		if len(taken) > 0 {
			if a.Number = issueNumber(taken[0]); len(taken) > 1 || a.Number <= 0 {
				return Args{}, fmt.Errorf("%s takes at most one issue number, not %q", d.Name, strings.Join(taken, " "))
			}
		}
	case AnyWords:
		a.Words = taken
	}
	return a, nil
}

// issueNumber reads N or #N; anything else is 0.
func issueNumber(word string) int {
	n, err := strconv.Atoi(strings.TrimPrefix(word, "#"))
	if err != nil {
		return 0
	}
	return n
}

// pending answers a Pick the call gave without a number, which the next word names.
func pending(values map[string]flag.Getter) *pickValue {
	for _, v := range values {
		if p, ok := v.(*pickValue); ok && p.v.Set && p.v.N == 0 {
			return p
		}
	}
	return nil
}

// pickName names the first Pick flag d declares, "" where it declares none.
func (d CommandDecl) pickName() string {
	for _, f := range d.Flags {
		if _, ok := f.Default.(Pick); ok {
			return f.Name
		}
	}
	return ""
}

// checkFlags refuses a flag declaration that has no name, no help, a type
// the collector does not parse, or the name of another.
func (d CommandDecl) checkFlags() []string {
	var errs []string
	seen := map[string]bool{}
	for _, f := range d.flags() {
		switch {
		case !portName(f.Name):
			errs = append(errs, fmt.Sprintf("command %q: flag %q is no name: letters, digits and dashes", d.Name, f.Name))
		case seen[f.Name]:
			errs = append(errs, fmt.Sprintf("command %q: flag --%s is declared twice", d.Name, f.Name))
		case strings.TrimSpace(f.Help) == "":
			errs = append(errs, fmt.Sprintf("command %q: flag --%s has no help", d.Name, f.Name))
		}
		seen[f.Name] = true
		switch f.Default.(type) {
		case string, bool, int, time.Duration, Pick:
		default:
			errs = append(errs, fmt.Sprintf("command %q: flag --%s is a %s: a flag is a string, bool, int, time.Duration or index.Pick", d.Name, f.Name, reflect.TypeOf(f.Default)))
		}
	}
	switch d.Words {
	case NoWords, Number, MaybeNumber, AnyWords:
	default:
		errs = append(errs, fmt.Sprintf("command %q takes words %q: none, %q, %q or %q", d.Name, d.Words, Number, MaybeNumber, AnyWords))
	}
	return errs
}

// pickValue is a Pick as a flag: alone, it is a switch; as --name=N, it names N.
type pickValue struct {
	name string
	v    Pick
}

func (p *pickValue) Set(v string) error {
	p.v.Set = true
	switch v {
	case "true":
		return nil
	case "false":
		p.v.Set = false
		return nil
	}
	if p.v.N = issueNumber(v); p.v.N <= 0 {
		return fmt.Errorf("--%s takes an issue number, not %q", p.name, v)
	}
	return nil
}
func (p *pickValue) String() string   { return "" }
func (p *pickValue) Get() any         { return p.v }
func (p *pickValue) IsBoolFlag() bool { return true }
