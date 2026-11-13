package index_test

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/index"
)

type limits struct {
	Max   int    `toml:"max"`
	Label string // read by its name, in any case
}

type settingsIn struct {
	Every  time.Duration     `index:"config/every"`
	Names  []string          `index:"config/names"`
	Limits limits            `index:"config/limits"`
	Ratio  float64           `index:"config/ratio"`
	Tags   map[string]bool   `index:"config/tags"`
	Any    any               `index:"config/any"`
	Small  uint8             `index:"config/small"`
	Deep   map[string][]int8 `index:"config/deep"`
}

var settings = index.Declare("settings", "Says its config back.",
	index.Config("every", time.Minute, "How often."),
	index.Config("names", []string(nil), "Some names."),
	index.Config("limits", limits{}, "Some limits."),
	index.Config("ratio", 0.5, "A ratio."),
	index.Config("tags", map[string]bool(nil), "Some tags."),
	index.Config("any", any(nil), "Anything."),
	index.Config("small", uint8(0), "A small number."),
	index.Config("deep", map[string][]int8(nil), "Nested numbers."),
	index.Derived("said", settingsIn{}, "The config, said back.", func(in settingsIn) (settingsIn, error) { return in, nil }),
)

// The wiring file is read at start, from the application's wiring.toml.
func TestTheWiringIsReadFromItsFileAtStart(t *testing.T) {
	t.Parallel()
	path := filepath.Join(t.TempDir(), index.WiringFile)
	must(t, os.WriteFile(path, []byte(`
# Config values, in TOML's own types, become the keys' Go types.
[instances.s]
component = "settings"

[instances.s.config]
every = "2m30s"
names = ["a", "b"]
limits = { max = 3, label = "top" }
ratio = 2
tags = { x = true }
any = [1, "two"]
small = 255
deep = { a = [1, -2] }
`), 0o600))
	w, err := index.ReadWiring(path)
	must(t, err)
	ix, err := index.Start(w, settings)
	must(t, err)
	want := settingsIn{
		Every: 150 * time.Second, Names: []string{"a", "b"}, Limits: limits{Max: 3, Label: "top"}, Ratio: 2,
		Tags: map[string]bool{"x": true}, Any: []any{int64(1), "two"}, Small: 255, Deep: map[string][]int8{"a": {1, -2}},
	}
	if got := read(t, ix, "s/said"); !reflect.DeepEqual(got.V, want) {
		t.Fatalf("s/said is %+v, want %+v", got.V, want)
	}
	if _, err := index.ReadWiring(filepath.Join(t.TempDir(), "none.toml")); err == nil {
		t.Fatal("a missing wiring file was read")
	}
}

// A placement names the command the core runs the instance with, and its line.
func TestAPlacementNamesItsCommand(t *testing.T) {
	t.Parallel()
	w, err := index.ParseWiring([]byte("[instances.pump]\ncomponent = \"pump\"\ncommand = [\"uv\", \"run\", \"pump\"]\n\n[instances.sum]\ncomponent = \"sum\"\n"))
	if err != nil {
		t.Fatal(err)
	}
	if got := w.Instances[0]; !reflect.DeepEqual(got.Command, []string{"uv", "run", "pump"}) || got.CommandLine != 3 {
		t.Fatalf("the placement reads as %q at line %d, and wants [uv run pump] at line 3", got.Command, got.CommandLine)
	}
	if got := w.Instances[1]; got.Command != nil {
		t.Fatalf("an instance without a command is placed with %q, and wants none: it runs in the core", got.Command)
	}
}

// A hook binds a host's event to the command that answers it, in the order of its lines.
func TestAHookBindsAnEventToItsCommand(t *testing.T) {
	t.Parallel()
	w, err := index.ParseWiring([]byte("[instances.sum]\ncomponent = \"sum\"\n\n[hooks]\nSubagentStop = \"sum check\"\nStop = \"sum check\"\n"))
	if err != nil {
		t.Fatal(err)
	}
	want := []index.Hook{{Event: "SubagentStop", Command: "sum check", Line: 5}, {Event: "Stop", Command: "sum check", Line: 6}}
	if !reflect.DeepEqual(w.Hooks, want) {
		t.Fatalf("the hooks read as %+v, and want %+v", w.Hooks, want)
	}
}

func TestABrokenWiringFileIsRefusedWithItsLine(t *testing.T) {
	t.Parallel()
	for _, c := range []struct{ wiring, want string }{
		{"[instances.a]\ncomponent = \"source\"\ncomponent = \"twice\"\n", "wiring line 3:"},
		{"[instances.a]\nmodule = \"source\"\n", "wiring line 2: instance a: no key module: an instance holds component, enabled, config and command"},
		{"[instances.a]\ncomponent = \"source\"\ncommand = []\n", "wiring line 3: instance a: command is a list of words, the program first"},
		{"[instances.a]\ncomponent = \"source\"\ncommand = \"pump\"\n", "wiring line 3: instance a: command is a list of words"},
		{"[instances.a]\ncomponent = \"source\"\ncommand = [\"pump\", 3]\n", "wiring line 3: instance a: command is a list of words"},
		{"[instances.a]\nenabled = false\n", "wiring line 1: instance a names no component"},
		{"[instances.a]\ncomponent = \"source\"\nenabled = \"no\"\n", "wiring line 3: instance a: enabled is true or false"},
		{"[instances.a]\ncomponent = 3\n", "wiring line 2: instance a: component is no name"},
		{"[instances.a]\ncomponent = \"source\"\nconfig = 3\n", "wiring line 3: instance a: config is no table"},
		{"instances = { a = 1 }\n", "wiring line 1: instance a is no table"},
		{"instances = 1\n", "wiring line 1: instances is no table"},
		{"\n[modules]\n", "wiring line 2: no key modules: a wiring holds [instances], [wires] and [hooks]"},
		{"[hooks]\n\"Stop.x\" = \"check\"\n", "wiring line 2: hook \"Stop.x\": an event is one word of letters"},
		{"[hooks]\nStop = 3\n", "wiring line 2: hook Stop names no command"},
		{"[hooks]\nStop = \" \"\n", "wiring line 2: hook Stop names no command"},
		{"hooks = 1\n", "wiring line 1: hooks is no table"},
		{"[wires]\n\"a.x\" = 3\n", "wiring line 2: wire a.x binds to no name, port, verb or built-in"},
		{"[wires]\n\"a.x\" = { builtin = true }\n", "wiring line 2: wire a.x binds to no name"},
		{"[wires]\n\"a.x\" = { to = \"n\", builtin = 1 }\n", "wiring line 2: wire a.x: builtin is true or false"},
		{"[wires]\n\"a.x\" = { to = \"n\", from = \"m\" }\n", "wiring line 2: wire a.x: no key from: a wire holds to and builtin"},
	} {
		if _, err := index.ParseWiring([]byte(c.wiring)); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("the wiring\n%s\nanswered %v, want %q", c.wiring, err, c.want)
		}
	}
	for _, c := range []struct{ config, want string }{
		{`every = 3`, `wiring line 6: instance s: config every takes time.Duration: a duration is a string such as "2m", not int64`},
		{`every = "soon"`, "config every takes time.Duration"},
		{`small = 256`, "config small takes uint8: 256 is no uint8"},
		{`small = -1`, "is no uint8"},
		{`names = "a"`, "a is no array"},
		{`names = [1]`, "item 1: 1 is no string"},
		{`limits = { max = 1, min = 0 }`, "has no field min"},
		{`limits = { max = "one" }`, "max: one is no int"},
		{`limits = 3`, "3 is no table"},
		{`ratio = "half"`, "half is no number"},
		{`tags = { x = 1 }`, "x: 1 is no bool"},
		{`tags = 1`, "is no table of map[string]bool"},
		{`deep = { a = [300] }`, "a: item 1: 300 is no int8"},
	} {
		refused(t, "\n[instances.s]\ncomponent = \"settings\"\n\n[instances.s.config]\n"+c.config+"\n", c.want, settings)
	}
	type fn func()
	refused(t, "[instances.s]\ncomponent = \"odd\"\nconfig = { f = 1 }\n", "a config key of type index_test.fn cannot be given in the wiring",
		index.Declare("odd", "Odd config.", index.Config("f", fn(nil), "A function.")))
}

// Instances and wires keep the order of their lines, whichever form the file uses.
func TestTheWiringKeepsItsLines(t *testing.T) {
	t.Parallel()
	w, err := index.ParseWiring([]byte(`
[instances.b]
component = "source"

[instances]
a.component = "doubler"
c = { component = "doubler", enabled = false, config = { k = 1 } }

[wires]
"c.x" = "b.n"
"a.x" = { to = "b.n", builtin = true }
`))
	must(t, err)
	want := index.Wiring{
		Instances: []index.Instance{
			{Name: "b", Component: "source", Enabled: true, Config: map[string]index.ConfigValue{}, Line: 2},
			{Name: "a", Component: "doubler", Enabled: true, Config: map[string]index.ConfigValue{}, Line: 6},
			{Name: "c", Component: "doubler", Enabled: false, OffLine: 7, Config: map[string]index.ConfigValue{"k": {Value: int64(1), Line: 7}}, Line: 7},
		},
		Wires: []index.Wire{{Port: "c.x", To: "b.n", Line: 10}, {Port: "a.x", To: "b.n", Builtin: true, Line: 11}},
	}
	if !reflect.DeepEqual(w, want) {
		t.Fatalf("the wiring reads\n%+v\nwant\n%+v", w, want)
	}
}

// Merge adds an overlay wiring's instances, wires and hooks to a base wiring,
// as cli reads .se/wiring.toml after wiring.toml for `se component add`'s ad
// hoc components.
func TestMergeAddsAnOverlaysInstancesWiresAndHooks(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	base := filepath.Join(dir, index.WiringFile)
	if err := os.WriteFile(base, []byte(
		"[instances.a]\ncomponent = \"a\"\n\n[wires]\n\"a.x\" = \"b/y\"\n\n[hooks]\nStop = \"a check\"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	overlay := filepath.Join(dir, "overlay.toml")
	if err := os.WriteFile(overlay, []byte(
		"[instances.probe]\ncomponent = \"probe\"\ncommand = [\"python\", \"-m\", \"kern\", \"run\", \".se/components/probe\"]\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	w, err := index.ReadWiring(base)
	if err != nil {
		t.Fatal(err)
	}
	o, err := index.ReadWiring(overlay)
	if err != nil {
		t.Fatal(err)
	}
	w.Merge(o)
	names := make([]string, 0, len(w.Instances))
	for _, in := range w.Instances {
		names = append(names, in.Name)
	}
	if !reflect.DeepEqual(names, []string{"a", "probe"}) {
		t.Fatalf("the merged instances are %v, and want [a probe]", names)
	}
	if len(w.Wires) != 1 || len(w.Hooks) != 1 {
		t.Fatalf("the merge kept %d wires and %d hooks, and wants the base's one each", len(w.Wires), len(w.Hooks))
	}
	var probe index.Instance
	for _, in := range w.Instances {
		if in.Name == "probe" {
			probe = in
		}
	}
	if len(probe.Command) == 0 {
		t.Fatalf("the overlay's placed instance lost its command: %+v", probe)
	}
}
