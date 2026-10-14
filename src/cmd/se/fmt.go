package main

import "github.com/mb-89/SE/src/internal/battery"

func init() {
	register(Command{
		Name:    "fmt",
		Usage:   "fmt",
		Group:   "Checks",
		Summary: "run every formatter tests/check.sh checks",
		Details: "install each pinned linter tests/tools.sh names that is missing or at another version, " +
			"as the battery does, then run their formatters over the checkout: golangci-lint fmt and biome check --write. " +
			"It fails where a formatter leaves a finding it cannot fix.",
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("fmt")); err != nil {
				return Reply{}, err
			}
			said, err := battery.Format(c.Workspace)
			if err != nil {
				return Reply{}, err
			}
			if said == "" {
				said = "fmt: formatted"
			}
			return Reply{Text: said}, nil
		},
	})
}
