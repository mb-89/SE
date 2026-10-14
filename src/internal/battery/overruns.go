package battery

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"io/fs"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/internal/io/disk"
)

// HookEvent is the event of a session log row that says how long a plugin
// hook took: its input names the hook and its milliseconds.
const HookEvent = "se.hook"

// Overrun is one se command or plugin hook that ran over its class's budget
// in a span of time: how often it ran, how often over, and by how much.
type Overrun struct {
	// Kind is "command" or "hook".
	Kind   string `json:"kind" yaml:"kind"`
	Name   string `json:"name" yaml:"name"`
	Class  string `json:"class" yaml:"class"`
	Budget int64  `json:"budget_ms" yaml:"budget_ms"`
	Hard   bool   `json:"hard,omitempty" yaml:"hard,omitempty"`
	Calls  int    `json:"calls" yaml:"calls"`
	Over   int    `json:"over" yaml:"over"`
	// Worst is its longest run; Excess the milliseconds its overruns took
	// beyond the budget, together.
	Worst  int64 `json:"worst_ms" yaml:"worst_ms"`
	Excess int64 `json:"excess_ms" yaml:"excess_ms"`
}

// Overruns measures what the workspace on d recorded after from and up to
// to, against the classes of its spec/budgets.yaml: each se command in its
// CallsFile and each hook in the se.hook rows of its daemon's session logs.
// It answers every command and hook that went over its class at least once,
// commands first, then by name. A workspace that holds no budgets, or
// recorded nothing, answers none; a command or hook in no class, or in one of
// 0ms, is left out (the se rule budgeted names the first).
func Overruns(d disk.Disk, workspace string, from, to time.Time) ([]Overrun, error) {
	budgets, err := ReadBudgets(d, workspace)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	tally := map[[2]string]*Overrun{}
	count := func(kind, name string, at time.Time, ms int64) {
		if !at.After(from) || at.After(to) {
			return
		}
		class := budgets.CommandClasses[name]
		if kind == "hook" {
			class = budgets.HookClasses[name]
		}
		budget, ok := budgets.Classes[class]
		if !ok || budget.Ms <= 0 {
			return
		}
		key := [2]string{kind, name}
		o := tally[key]
		if o == nil {
			o = &Overrun{Kind: kind, Name: name, Class: class, Budget: budget.Ms, Hard: budget.Hard}
			tally[key] = o
		}
		o.Calls++
		o.Worst = max(o.Worst, ms)
		if ms > budget.Ms {
			o.Over++
			o.Excess += ms - budget.Ms
		}
	}

	calls, err := lines(d, filepath.Join(workspace, filepath.FromSlash(CallsFile)))
	if err != nil {
		return nil, err
	}
	for _, line := range calls {
		var c Call
		if json.Unmarshal(line, &c) != nil || c.Name == "" {
			continue
		}
		count("command", c.Name, c.At, c.Ms)
	}

	logs := daemon.Paths{Workspace: workspace, Disk: d}.Logs()
	names, err := d.List(logs)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	for _, name := range names {
		if !strings.HasSuffix(name, ".jsonl") {
			continue
		}
		rows, err := lines(d, filepath.Join(logs, name))
		if err != nil {
			return nil, err
		}
		for _, line := range rows {
			var row struct {
				At    string `json:"at"`
				Event string `json:"event"`
				E     struct {
					Hook string   `json:"hook"`
					Ms   *float64 `json:"ms"`
				} `json:"e"`
			}
			if json.Unmarshal(line, &row) != nil || row.Event != HookEvent || row.E.Hook == "" || row.E.Ms == nil {
				continue
			}
			at, err := time.Parse(time.RFC3339Nano, row.At)
			if err != nil {
				continue
			}
			count("hook", row.E.Hook, at, int64(*row.E.Ms))
		}
	}

	var out []Overrun
	for _, o := range tally {
		if o.Over > 0 {
			out = append(out, *o)
		}
	}
	sort.Slice(out, func(a, b int) bool {
		if out[a].Kind != out[b].Kind {
			return out[a].Kind == "command"
		}
		return out[a].Name < out[b].Name
	})
	return out, nil
}

// lines answers the non-blank lines of the file at path; a file that is not
// there has none.
func lines(d disk.Disk, path string) ([][]byte, error) {
	data, err := d.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out [][]byte
	scan := bufio.NewScanner(bytes.NewReader(data))
	scan.Buffer(make([]byte, 0, 64*1024), 16*1024*1024)
	for scan.Scan() {
		if line := bytes.TrimSpace(scan.Bytes()); len(line) > 0 {
			out = append(out, append([]byte(nil), line...))
		}
	}
	return out, scan.Err()
}
