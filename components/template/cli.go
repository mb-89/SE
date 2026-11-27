package template

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"path/filepath"

	"kern/cli"
)

// Verb is the command line's door to the engine, `se template <fill|check>`: the request's JSON on
// stdin, of the shape the verb of that name takes (FillShape, CheckShape), and its answer's JSON on
// stdout, as the bus carries them. A caller in another language, such as SE's Python scripts
// through scripts/template_door.py, asks the Go engine through it and keeps no engine of its own.
// accept is no verb here: a Filled's seal holds only in the process that made it, so one run's
// fill is never another run's filled template.
var Verb = cli.Verb{
	Name: "template",
	Args: "fill|check [--root DIR] [--repository NAME] [--se DIR] < request.json",
	Doc:  "ask SE's template engine one verb: the request's JSON on stdin, its answer's JSON on stdout",
	Lead: true,
	Exit: "0 answered, 1 refused or failed (the reason on stderr), 2 a usage error",
	Flags: func(fs *flag.FlagSet) {
		fs.String("root", ".", "the checkout whose templates the engine reads")
		fs.String("repository", SERepository, "the repository the checkout's own templates are marked with")
		fs.String("se", "", "SE's checkout, the catalog's last layer; by default the root for SE's own")
	},
	Run: runVerb,
}

func runVerb(c *cli.Call) int {
	root, err := filepath.Abs(c.String("root"))
	if err != nil {
		fmt.Fprintf(c.Stderr, "%s template: %v\n", c.Name, err)
		return 2
	}
	s.mu.Lock()
	s.root, s.repository, s.se = root, c.String("repository"), c.String("se")
	s.mu.Unlock()
	answer, err := Ask(context.Background(), c.Lead, c.Stdin)
	if err != nil {
		fmt.Fprintf(c.Stderr, "%s template %s: %v\n", c.Name, c.Lead, err)
		if _, usage := err.(usageError); usage {
			return 2
		}
		return 1
	}
	out, err := json.Marshal(answer)
	if err != nil {
		fmt.Fprintf(c.Stderr, "%s template %s: %v\n", c.Name, c.Lead, err)
		return 1
	}
	fmt.Fprintf(c.Stdout, "%s\n", out)
	return 0
}

type usageError string

func (u usageError) Error() string { return string(u) }

// Ask answers the verb named of the request read as JSON from in, as the component's verb of that
// name answers it on the bus.
func Ask(ctx context.Context, verb string, in io.Reader) (any, error) {
	decoder := json.NewDecoder(in)
	switch verb {
	case "fill":
		var req FillRequest
		if err := decoder.Decode(&req); err != nil {
			return nil, fmt.Errorf("the request is no %s: %v", FillShape, err)
		}
		return fillVerb(ctx, req)
	case "check":
		var req CheckRequest
		if err := decoder.Decode(&req); err != nil {
			return nil, fmt.Errorf("the request is no %s: %v", CheckShape, err)
		}
		return checkVerb(ctx, req)
	}
	return nil, usageError(fmt.Sprintf("the verb is fill or check, not %q", verb))
}
