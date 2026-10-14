package battery

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
)

// CallsFile is where each se command records how long it took, one JSON line
// per call, under the workspace.
const CallsFile = ".se/.runtime/calls.jsonl"

// Call is one se command's run, measured against its class's budget.
type Call struct {
	At     time.Time `json:"at"`
	Name   string    `json:"name"`
	Ms     int64     `json:"ms"`
	Budget *Budget   `json:"budget,omitempty"`
	// Over is set when the call ran over its budget; Unbudgeted when
	// spec/budgets.yaml, which the workspace holds, names no class for it.
	Over       bool `json:"over,omitempty"`
	Unbudgeted bool `json:"unbudgeted,omitempty"`
}

// Overrun says how far the call went over its budget, or "" where it did not.
func (c Call) Overrun() string {
	if !c.Over {
		return ""
	}
	return fmt.Sprintf("%s took %dms, over its budget of %dms (%s)", c.Name, c.Ms, c.Budget.Ms, BudgetsFile)
}

// Record measures the call against the budgets of the workspace on d, where
// it holds them, and appends it to its CallsFile. A workspace whose runtime
// folder does not exist records nothing: se makes no folder to time itself.
func Record(d disk.Disk, workspace string, c Call) (Call, error) {
	at := filepath.Join(workspace, filepath.FromSlash(CallsFile))
	if there, err := d.Exists(filepath.Dir(at)); err != nil || !there {
		return c, err
	}
	budgets, err := ReadBudgets(d, workspace)
	switch {
	case errors.Is(err, fs.ErrNotExist):
	case err != nil:
		return c, err
	default:
		if budget, ok := budgets.Command(c.Name); ok {
			c.Budget = &budget
			c.Over = budget.Ms > 0 && c.Ms > budget.Ms
		} else {
			c.Unbudgeted = true
		}
	}
	line, err := json.Marshal(c)
	if err != nil {
		return c, err
	}
	f, err := d.Append(at)
	if err != nil {
		return c, err
	}
	if _, err := f.Write(append(line, '\n')); err != nil {
		_ = f.Close()
		return c, err
	}
	return c, f.Close()
}
