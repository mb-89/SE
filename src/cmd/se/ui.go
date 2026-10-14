package main

import (
	"fmt"

	"github.com/mb-89/SE/src/index"
)

// columnsKey is the cli instance's config key for the most buttons a row of
// /se ui holds; defaultColumns is its built-in value, which the wiring file sets.
const (
	columnsKey     = "columns"
	defaultColumns = 3
)

func init() {
	register(Command{
		Name:    "ui",
		Class:   interactive,
		Usage:   "ui",
		Group:   "Session",
		Summary: "open SE's control panel: the on/off toggle and the commands",
		Details: "open SE's control panel, a grid of buttons every surface draws, the phone included: the on/off toggle top left, then a button for each command registered as one (a command that takes no typed words), each labelled with its name. A row holds at most the cli instance's columns config value (cli/config/columns) and the next button starts the next row; every cell is as wide as every other, so the columns align from row to row and a short last row stays to the left. A press runs what typing /se <name> runs.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("ui")); err != nil {
				return Reply{}, err
			}
			columns, err := panelColumns(index.Wired)
			if err != nil {
				return Reply{}, err
			}
			return Reply{Text: "SE's control panel is open.", Panel: &Panel{Buttons: buttons(), Columns: columns}}, nil
		},
	})
}

// buttons names the commands /se ui offers as buttons, as the index's catalog holds them.
func buttons() []string {
	out := []string{}
	for _, c := range catalog().Buttons() {
		out = append(out, c.Name)
	}
	return out
}

// panelColumns answers the most buttons a row of /se ui holds, the cli
// instance's columns config value in the wiring wired gives. It starts an
// index of the cli instance alone, so it needs no other module.
func panelColumns(wired func() (index.Wiring, error)) (int, error) {
	w, err := wired()
	if err != nil {
		return 0, err
	}
	m := cliModule()
	own, instance := index.Wiring{}, ""
	for _, in := range w.Instances {
		if in.Module == m.Name() {
			own.Instances, instance = append(own.Instances, in), in.Name
		}
	}
	if instance == "" {
		return 0, fmt.Errorf("the wiring has no %s instance to read %s from", m.Name(), columnsKey)
	}
	ix, err := index.Start(own, m)
	if err != nil {
		return 0, err
	}
	name := instance + "/" + index.ConfigPrefix + columnsKey
	v, err := ix.Read(name)
	if err != nil {
		return 0, err
	}
	n, ok := v.V.(int)
	if !ok || n < 1 {
		return 0, fmt.Errorf("%s is no count of columns: %v", name, v.V)
	}
	return n, nil
}
