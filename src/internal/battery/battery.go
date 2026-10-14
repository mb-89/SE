// Package battery profiles tests/check.sh: how long each step took, each
// Go test and each plugin test, measured against the soft budgets in spec/budgets.yaml. check.sh
// writes the raw durations into Dir; Report reads them back, and the profile it
// writes there is what the CI summary, the PR body and the landing facts show.
package battery

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"

	"github.com/mb-89/SE/src/internal/io/disk"
)

const (
	// BudgetsFile holds a budget per battery step and one for the total.
	BudgetsFile = "spec/budgets.yaml"
	// Dir is where check.sh writes the battery's durations, under the workspace.
	Dir = ".se/.runtime/battery"
	// StepsFile has one line per step check.sh ran: its name, a tab, its milliseconds.
	StepsFile = "steps.tsv"
	// GoTestFile is go test -json's output for the battery's Go tests.
	GoTestFile = "gotest.json"
	// ProfileFile is the profile Report writes, machine-readable; MarkdownFile the same for a person.
	ProfileFile  = "profile.json"
	MarkdownFile = "profile.md"
	// Slowest is how many of the slowest tests a profile names.
	Slowest = 10
)

// Budget is how long a step may take, in milliseconds. A soft budget's
// overrun is reported; a hard one's fails the battery.
type Budget struct {
	Ms   int64 `yaml:"ms" json:"ms"`
	Hard bool  `yaml:"hard" json:"hard"`
}

// Budgets are spec/budgets.yaml: one for the battery's total, one per step
// by its name, the interactive commands', and a class for each se command
// and each plugin hook.
type Budgets struct {
	Total    Budget            `yaml:"total"`
	Steps    map[string]Budget `yaml:"steps"`
	Commands CommandBudgets    `yaml:"commands"`
	// Classes are budgets by what a call waits on; CommandClasses and
	// HookClasses name the class of each se command and each plugin hook.
	Classes        map[string]Budget `yaml:"classes"`
	CommandClasses map[string]string `yaml:"command_classes"`
	HookClasses    map[string]string `yaml:"hook_classes"`
}

// Command answers the budget of the se command named, through its class; ok
// is false where it has none.
func (b Budgets) Command(name string) (budget Budget, ok bool) {
	budget, ok = b.Classes[b.CommandClasses[name]]
	return budget, ok
}

// CommandBudgets hold every interactive command (principle 9): the battery
// runs each against the fake GitHub, each request and each process start
// delayed by Latency, and fails one over Interactive, unless Over names it.
type CommandBudgets struct {
	Interactive CommandBudget `yaml:"interactive" json:"interactive"`
	Latency     Latency       `yaml:"latency" json:"latency"`
	// Over names the interactive commands that still run over; it only shrinks.
	Over []string `yaml:"over" json:"over"`
}

// CommandBudget is how long one run of a command may take, and how many
// outside requests (GitHub requests and process starts) it may make.
type CommandBudget struct {
	Ms       int64 `yaml:"ms" json:"ms"`
	Requests int   `yaml:"requests" json:"requests"`
}

// Latency is what the fakes add to each request to GitHub and each process start.
type Latency struct {
	RequestMs int64 `yaml:"request_ms" json:"request_ms"`
	ProcessMs int64 `yaml:"process_ms" json:"process_ms"`
}

// Command is one interactive command's run in the battery: its outside
// requests and how long it took on the fakes' clock.
type Command struct {
	Name     string `json:"name"`
	Requests int    `json:"requests"`
	Ms       int64  `json:"ms"`
}

// CommandMark starts the line a test writes for each command it measured,
// which the profile reads from go test's output.
const CommandMark = "battery-command:"

// CommandLine is the line a test logs for a command it measured.
func CommandLine(c Command) string {
	return fmt.Sprintf("%s %s\t%d\t%d", CommandMark, c.Name, c.Requests, c.Ms)
}

// ParseCommands reads go test -json's events for the lines CommandLine wrote:
// each command measured, once, by its name.
func ParseCommands(r io.Reader) ([]Command, error) {
	byName := map[string]Command{}
	lines := bufio.NewScanner(r)
	lines.Buffer(make([]byte, 0, 64<<10), 16<<20)
	for lines.Scan() {
		var e struct {
			Action string `json:"Action"`
			Output string `json:"Output"`
		}
		if json.Unmarshal(lines.Bytes(), &e) != nil || e.Action != "output" {
			continue
		}
		_, line, ok := strings.Cut(e.Output, CommandMark)
		if !ok {
			continue
		}
		f := strings.Split(strings.TrimSpace(line), "\t")
		if len(f) != 3 {
			continue
		}
		n, err1 := strconv.Atoi(f[1])
		ms, err2 := strconv.ParseInt(f[2], 10, 64)
		if err1 == nil && err2 == nil {
			byName[f[0]] = Command{Name: f[0], Requests: n, Ms: ms}
		}
	}
	out := make([]Command, 0, len(byName))
	for _, c := range byName {
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, lines.Err()
}

// Step is one step of the battery and how long it took.
type Step struct {
	Name   string  `json:"name"`
	Ms     int64   `json:"ms"`
	Budget *Budget `json:"budget,omitempty"`
}

// Test is one Go test, or one plugin test, and how long it took. A plugin
// test's Package is the file it is in.
type Test struct {
	Package string `json:"package"`
	Name    string `json:"name"`
	Ms      int64  `json:"ms"`
}

func (t Test) String() string { return fmt.Sprintf("%s %s %dms", t.Package, t.Name, t.Ms) }

// Profile is one battery run: its steps, its total, its slowest tests, and
// every budget it ran over.
type Profile struct {
	TotalMs     int64   `json:"total_ms"`
	TotalBudget *Budget `json:"total_budget,omitempty"`
	Steps       []Step  `json:"steps"`
	Slowest     []Test  `json:"slowest_tests"`
	// SlowestPlugin are the slowest plugin (bun) tests, beside the Go tests.
	SlowestPlugin []Test `json:"slowest_plugin_tests"`
	// Commands are the interactive commands' runs, against CommandBudget.
	Commands      []Command      `json:"commands"`
	CommandBudget *CommandBudget `json:"command_budget,omitempty"`
	// Overruns names each budget the run went over; Hard those of them that fail it.
	Overruns []string `json:"overruns"`
	Hard     []string `json:"hard_overruns"`
	// Unbudgeted names each step spec/budgets.yaml gives no budget.
	Unbudgeted []string `json:"unbudgeted"`
}

// ReadBudgets reads the budgets file in dir on d.
func ReadBudgets(d disk.Disk, dir string) (Budgets, error) {
	data, err := d.ReadFile(filepath.Join(dir, BudgetsFile))
	if err != nil {
		return Budgets{}, err
	}
	var b Budgets
	if err := yaml.Unmarshal(data, &b); err != nil {
		return Budgets{}, fmt.Errorf("%s: %v", BudgetsFile, err)
	}
	return b, nil
}

// ParseSteps reads the steps file: a step per line, its name, a tab, its milliseconds.
func ParseSteps(r io.Reader) ([]Step, error) {
	var steps []Step
	lines := bufio.NewScanner(r)
	for lines.Scan() {
		line := strings.TrimSpace(lines.Text())
		if line == "" {
			continue
		}
		name, ms, ok := strings.Cut(line, "\t")
		n, err := strconv.ParseInt(ms, 10, 64)
		if !ok || err != nil {
			return nil, fmt.Errorf("%s: %q is no step: a name, a tab and milliseconds", StepsFile, line)
		}
		steps = append(steps, Step{Name: name, Ms: n})
	}
	return steps, lines.Err()
}

// event is the part of a go test -json event a profile reads.
type event struct {
	Action  string  `json:"Action"`
	Package string  `json:"Package"`
	Test    string  `json:"Test"`
	Elapsed float64 `json:"Elapsed"`
}

// ParseGoTest reads go test -json's events: every test that passed or failed,
// and how long it took. A line that is no event is skipped.
func ParseGoTest(r io.Reader) ([]Test, error) {
	var tests []Test
	lines := bufio.NewScanner(r)
	lines.Buffer(make([]byte, 0, 64<<10), 16<<20)
	for lines.Scan() {
		var e event
		if json.Unmarshal(lines.Bytes(), &e) != nil || e.Test == "" {
			continue
		}
		if e.Action == "pass" || e.Action == "fail" {
			tests = append(tests, Test{Package: e.Package, Name: e.Test, Ms: int64(e.Elapsed*1000 + 0.5)})
		}
	}
	return tests, lines.Err()
}

// Build profiles a run: its steps against their budgets, its total against
// the total's, and its slowest Go and plugin tests, slowest first.
func Build(steps []Step, tests, pluginTests []Test, b Budgets) Profile {
	p := Profile{Steps: steps, Overruns: []string{}, Hard: []string{}, Unbudgeted: []string{}}
	over := func(what string, ms int64, budget Budget) {
		if budget.Ms <= 0 || ms <= budget.Ms {
			return
		}
		line := fmt.Sprintf("%s took %dms, over its budget of %dms", what, ms, budget.Ms)
		p.Overruns = append(p.Overruns, line)
		if budget.Hard {
			p.Hard = append(p.Hard, line)
		}
	}
	for i, s := range p.Steps {
		p.TotalMs += s.Ms
		if budget, ok := b.Steps[s.Name]; ok {
			p.Steps[i].Budget = &budget
			over("step "+s.Name, s.Ms, budget)
		} else {
			p.Unbudgeted = append(p.Unbudgeted, fmt.Sprintf("step %s has no budget in %s", s.Name, BudgetsFile))
		}
	}
	if b.Total.Ms > 0 {
		p.TotalBudget = &b.Total
		over("the battery", p.TotalMs, b.Total)
	}
	p.Slowest, p.SlowestPlugin = slowest(tests), slowest(pluginTests)
	return p
}

// slowest are the Slowest of tests, slowest first.
func slowest(tests []Test) []Test {
	s := append([]Test{}, tests...)
	sort.SliceStable(s, func(i, j int) bool { return s[i].Ms > s[j].Ms })
	if len(s) > Slowest {
		s = s[:Slowest]
	}
	return s
}

// Text is the profile as check.sh prints it.
func (p Profile) Text() string {
	var b strings.Builder
	fmt.Fprintf(&b, "battery: %dms in total%s\n", p.TotalMs, of(p.TotalBudget))
	for _, s := range p.Steps {
		fmt.Fprintf(&b, "battery: step %s %dms%s\n", s.Name, s.Ms, of(s.Budget))
	}
	fmt.Fprintf(&b, "battery: the %d slowest tests\n", len(p.Slowest))
	for _, t := range p.Slowest {
		fmt.Fprintf(&b, "battery:   %dms %s %s\n", t.Ms, t.Package, t.Name)
	}
	fmt.Fprintf(&b, "battery: the %d slowest plugin tests\n", len(p.SlowestPlugin))
	for _, t := range p.SlowestPlugin {
		fmt.Fprintf(&b, "battery:   %dms %s %s\n", t.Ms, t.Package, t.Name)
	}
	if len(p.Commands) > 0 {
		fmt.Fprintf(&b, "battery: the %d interactive commands%s\n", len(p.Commands), p.commandBudget())
	}
	for _, c := range p.Commands {
		fmt.Fprintf(&b, "battery:   %dms %d requests se %s\n", c.Ms, c.Requests, c.Name)
	}
	for _, o := range p.Overruns {
		fmt.Fprintf(&b, "battery: OVER BUDGET: %s\n", o)
	}
	for _, u := range p.Unbudgeted {
		fmt.Fprintf(&b, "battery: NO BUDGET: %s\n", u)
	}
	return b.String()
}

// commandBudget names the interactive commands' budget; nothing where there is none.
func (p Profile) commandBudget() string {
	if p.CommandBudget == nil {
		return ""
	}
	return fmt.Sprintf(" (budget %dms and %d requests each)", p.CommandBudget.Ms, p.CommandBudget.Requests)
}

// Markdown is the profile as the CI summary and the PR body show it.
func (p Profile) Markdown() string {
	var b strings.Builder
	fmt.Fprintf(&b, "### Battery profile\n\nTotal: **%dms**%s\n", p.TotalMs, of(p.TotalBudget))
	for _, o := range p.Overruns {
		fmt.Fprintf(&b, "\n> **Over budget:** %s", o)
	}
	for _, u := range p.Unbudgeted {
		fmt.Fprintf(&b, "\n> **No budget:** %s", u)
	}
	if len(p.Overruns)+len(p.Unbudgeted) > 0 {
		b.WriteString("\n")
	}
	b.WriteString("\n| step | ms | budget |\n|---|---:|---:|\n")
	for _, s := range p.Steps {
		budget := ""
		if s.Budget != nil {
			budget = strconv.FormatInt(s.Budget.Ms, 10)
		}
		fmt.Fprintf(&b, "| %s | %d | %s |\n", s.Name, s.Ms, budget)
	}
	fmt.Fprintf(&b, "\nThe %d slowest tests:\n\n| test | package | ms |\n|---|---|---:|\n", len(p.Slowest))
	for _, t := range p.Slowest {
		fmt.Fprintf(&b, "| %s | %s | %d |\n", t.Name, t.Package, t.Ms)
	}
	fmt.Fprintf(&b, "\nThe %d slowest plugin tests:\n\n| test | file | ms |\n|---|---|---:|\n", len(p.SlowestPlugin))
	for _, t := range p.SlowestPlugin {
		fmt.Fprintf(&b, "| %s | %s | %d |\n", strings.ReplaceAll(t.Name, "|", "\\|"), t.Package, t.Ms)
	}
	if len(p.Commands) > 0 {
		fmt.Fprintf(&b, "\nThe %d interactive commands%s:\n\n| command | requests | ms |\n|---|---:|---:|\n", len(p.Commands), p.commandBudget())
		for _, c := range p.Commands {
			fmt.Fprintf(&b, "| se %s | %d | %d |\n", c.Name, c.Requests, c.Ms)
		}
	}
	return b.String()
}

// of names a budget beside what it bounds; nothing where there is none.
func of(b *Budget) string {
	if b == nil || b.Ms <= 0 {
		return ""
	}
	kind := "soft"
	if b.Hard {
		kind = "hard"
	}
	return fmt.Sprintf(" (%s budget %dms)", kind, b.Ms)
}

// Report profiles the battery check.sh just ran in dir on d: it reads the
// durations and the budgets, writes the profile into Dir and, where summary
// is not nil, its Markdown there too. It fails only on a hard budget's overrun.
func Report(d disk.Disk, dir string, summary io.Writer) (Profile, error) {
	at := filepath.Join(dir, Dir)
	f, err := d.ReadFile(filepath.Join(at, StepsFile))
	if err != nil {
		return Profile{}, err
	}
	steps, err := ParseSteps(bytes.NewReader(f))
	if err != nil {
		return Profile{}, err
	}
	var tests []Test
	var commands []Command
	if g, err := d.ReadFile(filepath.Join(at, GoTestFile)); err == nil {
		if tests, err = ParseGoTest(bytes.NewReader(g)); err != nil {
			return Profile{}, err
		}
		if commands, err = ParseCommands(bytes.NewReader(g)); err != nil {
			return Profile{}, err
		}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return Profile{}, err
	}
	pluginTests, err := parsed(d, filepath.Join(at, PluginTestFile), ParsePluginTest)
	if err != nil {
		return Profile{}, err
	}
	budgets, err := ReadBudgets(d, dir)
	if err != nil {
		return Profile{}, err
	}
	p := Build(steps, tests, pluginTests, budgets)
	p.Commands = commands
	if len(commands) > 0 {
		p.CommandBudget = &budgets.Commands.Interactive
	}
	data, err := json.MarshalIndent(p, "", "  ")
	if err != nil {
		return Profile{}, err
	}
	if err := d.WriteFile(filepath.Join(at, ProfileFile), append(data, '\n')); err != nil {
		return Profile{}, err
	}
	if err := d.WriteFile(filepath.Join(at, MarkdownFile), []byte(p.Markdown())); err != nil {
		return Profile{}, err
	}
	if summary != nil {
		if _, err := io.WriteString(summary, p.Markdown()); err != nil {
			return Profile{}, err
		}
	}
	if len(p.Hard) > 0 {
		return p, fmt.Errorf("over a hard budget: %s", strings.Join(p.Hard, "; "))
	}
	return p, nil
}

// parsed reads the tests in the file at path with parse; none where there is no file.
func parsed(d disk.Disk, path string, parse func(io.Reader) ([]Test, error)) ([]Test, error) {
	data, err := d.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return parse(bytes.NewReader(data))
}

// Load reads the profile the last battery run in dir on d wrote; ok is false where there is none.
func Load(d disk.Disk, dir string) (p Profile, ok bool, err error) {
	data, err := d.ReadFile(filepath.Join(dir, Dir, ProfileFile))
	if errors.Is(err, fs.ErrNotExist) {
		return Profile{}, false, nil
	}
	if err != nil {
		return Profile{}, false, err
	}
	if err := json.Unmarshal(data, &p); err != nil {
		return Profile{}, false, fmt.Errorf("%s: %v", ProfileFile, err)
	}
	return p, true, nil
}
