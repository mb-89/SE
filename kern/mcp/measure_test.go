package mcp

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
	"kern/host"
)

// untouched is a core the test fails on the moment anything asks it:
// Listed starts nothing, leases nothing and calls nothing.
type untouched struct{ t *testing.T }

func (u untouched) Start() (host.Started, error) {
	u.t.Error("Listed asked the core to start")
	return host.Running, nil
}

func (u untouched) Status() (host.Status, error) {
	u.t.Error("Listed asked the core's status")
	return host.Status{}, nil
}

func (u untouched) Lease(string, bool) error {
	u.t.Error("Listed asked the core for a lease")
	return nil
}

func (u untouched) Call(context.Context, string, []string) (host.CallAnswer, error) {
	u.t.Error("Listed called the core")
	return host.CallAnswer{}, nil
}

func (u untouched) Get(context.Context, string) (host.NameValue, error) {
	u.t.Error("Listed read a name of the core")
	return host.NameValue{}, nil
}

// The measure on made-up tools: their count and order as given, each
// description's bytes and characters, each tool's bytes as its JSON, and
// the sum of those.
func TestTheMeasureCountsEachToolAndTheirSum(t *testing.T) {
	tools := []*sdk.Tool{
		{Name: "zeta", Description: "abc", InputSchema: map[string]any{"type": "object"}},
		{Name: "alpha", Description: "größer", InputSchema: map[string]any{"type": "object"}},
	}
	s, err := Measure(tools)
	if err != nil {
		t.Fatal(err)
	}
	zeta, _ := json.Marshal(tools[0])
	alpha, _ := json.Marshal(tools[1])
	want := Surface{
		Count: 2,
		Order: []string{"zeta", "alpha"},
		Tools: []ToolSize{{Name: "zeta", Description: 3, Runes: 3, Served: len(zeta)}, {Name: "alpha", Description: 8, Runes: 6, Served: len(alpha)}},
		Total: len(zeta) + len(alpha),
	}
	if !reflect.DeepEqual(s, want) {
		t.Fatalf("the measure answers %+v, and wants %+v", s, want)
	}
	if none, _ := Measure(nil); none.Count != 0 || none.Total != 0 || len(none.Tools) != 0 {
		t.Fatalf("no tools measure %+v, and want nothing", none)
	}
}

// A budget unset holds nothing, whatever the sizes; each number set names
// what exceeds it.
func TestTheBudgetHoldsOnlyTheNumbersSet(t *testing.T) {
	s := Surface{Count: 3, Tools: []ToolSize{{Name: "a", Description: 10}, {Name: "b", Description: 30}, {Name: "c", Description: 20}}, Total: 500}
	if over := s.Over(Budget{}); len(over) != 0 {
		t.Fatalf("an unset budget answers %q, and wants nothing", over)
	}
	if over := s.Over(Budget{Tools: 3, Description: 30, Total: 500}); len(over) != 0 {
		t.Fatalf("a budget met exactly answers %q, and wants nothing", over)
	}
	over := s.Over(Budget{Tools: 2, Description: 15, Total: 499})
	want := []string{
		"3 tools, and the budget allows 2",
		"tool b's description takes 30 bytes, and the budget allows 15",
		"tool c's description takes 20 bytes, and the budget allows 15",
		"the list takes 500 bytes, and the budget allows 499",
	}
	if !reflect.DeepEqual(over, want) {
		t.Fatalf("the budget answers %q, and wants %q", over, want)
	}
}

func TestTheTableHasARowPerToolAndTheSum(t *testing.T) {
	s := Surface{Count: 2, Order: []string{"a", "b"}, Tools: []ToolSize{{Name: "a", Description: 3, Runes: 3, Served: 40}, {Name: "b", Description: 8, Runes: 6, Served: 50}}, Total: 90}
	want := "| # | tool | description bytes | description characters | served bytes |\n|---|---|---|---|---|\n" +
		"| 1 | `a` | 3 | 3 | 40 |\n| 2 | `b` | 8 | 6 | 50 |\n| | 2 tools | 11 | | 90 |\n"
	if got := s.Table(); got != want {
		t.Fatalf("the table reads\n%s\nand wants\n%s", got, want)
	}
}

// Listed answers the tools of tools/list, byte for byte what
// testdata/door.json holds of the served door, and the same twice, while the
// core is never asked anything.
func TestListedIsTheServedListAndAsksNoCore(t *testing.T) {
	o := options(untouched{t}, catalog(t))
	var runs [][]byte
	for range 2 {
		tools, err := Listed(context.Background(), o)
		if err != nil {
			t.Fatal(err)
		}
		data, err := json.Marshal(tools)
		if err != nil {
			t.Fatal(err)
		}
		runs = append(runs, data)
	}
	if !bytes.Equal(runs[0], runs[1]) {
		t.Fatalf("two lists differ:\n%s\n%s", runs[0], runs[1])
	}
	raw, err := os.ReadFile(filepath.Join("testdata", "door.json"))
	if err != nil {
		t.Fatal(err)
	}
	var served struct {
		Tools any `json:"tools/list tools"`
	}
	if err := json.Unmarshal(raw, &served); err != nil {
		t.Fatal(err)
	}
	var listed any
	if err := json.Unmarshal(runs[0], &listed); err != nil {
		t.Fatal(err)
	}
	want, _ := json.MarshalIndent(served.Tools, "", "  ")
	got, _ := json.MarshalIndent(listed, "", "  ")
	if !bytes.Equal(got, want) {
		t.Fatalf("Listed answers\n%s\nand the served door\n%s", got, want)
	}
}

// A catalog the check refuses lists the tools the door would serve all the
// same, and the refusal goes to the log.
func TestListedSaysACatalogRefusalAndListsAllTheSame(t *testing.T) {
	o := options(untouched{t}, catalog(t))
	o.Greeting = []string{"desk sync"} // a command not declared read-only
	var log strings.Builder
	o.Log = &log
	tools, err := Listed(context.Background(), o)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, tool := range tools {
		names = append(names, tool.Name)
	}
	if got := strings.Join(names, " "); got != "desk status" {
		t.Fatalf("Listed answers %q, and wants desk and status", got)
	}
	if !strings.Contains(log.String(), "not declared read-only") {
		t.Fatalf("the log reads %q, and wants the catalog check's refusal", log.String())
	}
}
