// Package battery profiles tests/check.sh: how long each step took, and each
// Go test, measured against the soft budgets in spec/budgets.yaml. check.sh
// writes the raw durations into Dir; Report reads them back, and the profile it
// writes there is what the CI summary, the PR body and the landing facts show.
package battery

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
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

// Budgets are spec/budgets.yaml: one for the battery's total, one per step by its name.
type Budgets struct {
	Total Budget            `yaml:"total"`
	Steps map[string]Budget `yaml:"steps"`
}

// Step is one step of the battery and how long it took.
type Step struct {
	Name   string  `json:"name"`
	Ms     int64   `json:"ms"`
	Budget *Budget `json:"budget,omitempty"`
}

// Test is one Go test and how long it took.
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
	// Overruns names each budget the run went over; Hard those of them that fail it.
	Overruns []string `json:"overruns"`
	Hard     []string `json:"hard_overruns"`
}

// ReadBudgets reads the budgets file in dir.
func ReadBudgets(dir string) (Budgets, error) {
	data, err := os.ReadFile(filepath.Join(dir, BudgetsFile))
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
// the total's, and its slowest tests, slowest first.
func Build(steps []Step, tests []Test, b Budgets) Profile {
	p := Profile{Steps: steps, Overruns: []string{}, Hard: []string{}}
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
		}
	}
	if b.Total.Ms > 0 {
		p.TotalBudget = &b.Total
		over("the battery", p.TotalMs, b.Total)
	}
	p.Slowest = append([]Test{}, tests...)
	sort.SliceStable(p.Slowest, func(i, j int) bool { return p.Slowest[i].Ms > p.Slowest[j].Ms })
	if len(p.Slowest) > Slowest {
		p.Slowest = p.Slowest[:Slowest]
	}
	return p
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
	for _, o := range p.Overruns {
		fmt.Fprintf(&b, "battery: OVER BUDGET: %s\n", o)
	}
	return b.String()
}

// Markdown is the profile as the CI summary and the PR body show it.
func (p Profile) Markdown() string {
	var b strings.Builder
	fmt.Fprintf(&b, "### Battery profile\n\nTotal: **%dms**%s\n", p.TotalMs, of(p.TotalBudget))
	for _, o := range p.Overruns {
		fmt.Fprintf(&b, "\n> **Over budget:** %s", o)
	}
	if len(p.Overruns) > 0 {
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

// Report profiles the battery check.sh just ran in dir: it reads the
// durations and the budgets, writes the profile into Dir and, where summary
// is not nil, its Markdown there too. It fails only on a hard budget's overrun.
func Report(dir string, summary io.Writer) (Profile, error) {
	at := filepath.Join(dir, Dir)
	f, err := os.Open(filepath.Join(at, StepsFile))
	if err != nil {
		return Profile{}, err
	}
	steps, err := ParseSteps(f)
	f.Close()
	if err != nil {
		return Profile{}, err
	}
	var tests []Test
	if g, err := os.Open(filepath.Join(at, GoTestFile)); err == nil {
		tests, err = ParseGoTest(g)
		g.Close()
		if err != nil {
			return Profile{}, err
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return Profile{}, err
	}
	budgets, err := ReadBudgets(dir)
	if err != nil {
		return Profile{}, err
	}
	p := Build(steps, tests, budgets)
	data, err := json.MarshalIndent(p, "", "  ")
	if err != nil {
		return Profile{}, err
	}
	if err := os.WriteFile(filepath.Join(at, ProfileFile), append(data, '\n'), 0o644); err != nil {
		return Profile{}, err
	}
	if err := os.WriteFile(filepath.Join(at, MarkdownFile), []byte(p.Markdown()), 0o644); err != nil {
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

// Load reads the profile the last battery run in dir wrote; ok is false where there is none.
func Load(dir string) (p Profile, ok bool, err error) {
	data, err := os.ReadFile(filepath.Join(dir, Dir, ProfileFile))
	if errors.Is(err, os.ErrNotExist) {
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
