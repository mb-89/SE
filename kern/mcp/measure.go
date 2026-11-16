package mcp

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"unicode/utf8"

	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

// Listed answers the tool list the door serves for o, as tools/list answers
// it, in its order: the door's own server, asked by the SDK's client over an
// in-memory connection. It starts no core, takes no lease and calls no tool:
// o.Core is never touched. A catalog the check refuses still lists the tools
// the door would serve, the refusal said on o.Log as Serve says it.
func Listed(ctx context.Context, o Options) ([]*sdk.Tool, error) {
	if o.Log == nil {
		o.Log = io.Discard
	}
	d := &door{o: o, pages: map[string][]string{}, wake: make(chan struct{}, 1)}
	server, err := d.server()
	if err != nil {
		fmt.Fprintf(o.Log, "%s mcp: %v\n", o.App, err)
	}
	ct, st := sdk.NewInMemoryTransports()
	ss, err := server.Connect(ctx, st, nil)
	if err != nil {
		return nil, err
	}
	defer ss.Close()
	cs, err := sdk.NewClient(&sdk.Implementation{Name: o.App + " mcp --tools", Version: "0"}, nil).Connect(ctx, ct, nil)
	if err != nil {
		return nil, err
	}
	defer cs.Close()
	var tools []*sdk.Tool
	params := &sdk.ListToolsParams{}
	for {
		page, err := cs.ListTools(ctx, params)
		if err != nil {
			return nil, err
		}
		tools = append(tools, page.Tools...)
		if page.NextCursor == "" {
			return tools, nil
		}
		params = &sdk.ListToolsParams{Cursor: page.NextCursor}
	}
}

// ToolSize is one tool's share of the list: the bytes of its description,
// its runes (a host that cuts counts characters), and the bytes of the tool
// as served, its JSON.
type ToolSize struct {
	Name               string
	Description, Runes int
	Served             int
}

// Surface is what a tool list costs every turn: how many tools, in which
// order, each one's size, and the sum of their served bytes.
type Surface struct {
	Count int
	Order []string
	Tools []ToolSize
	Total int
}

// Measure measures a tool list in its order. It is pure: no I/O, only each
// tool's JSON as the SDK writes it.
func Measure(tools []*sdk.Tool) (Surface, error) {
	s := Surface{Count: len(tools)}
	for _, t := range tools {
		data, err := json.Marshal(t)
		if err != nil {
			return Surface{}, fmt.Errorf("tool %s: %v", t.Name, err)
		}
		s.Order = append(s.Order, t.Name)
		s.Tools = append(s.Tools, ToolSize{Name: t.Name, Description: len(t.Description), Runes: utf8.RuneCountInString(t.Description), Served: len(data)})
		s.Total += len(data)
	}
	return s, nil
}

// Budget is the most a tool list may cost: tools, bytes of one description,
// bytes of the whole list (Surface.Total). A number unset, 0, holds nothing.
type Budget struct {
	Tools, Description, Total int
}

// Over answers each way the surface exceeds the budget, one line each, in
// the order of Budget's fields; none where it fits or the budget is unset.
func (s Surface) Over(b Budget) []string {
	var over []string
	if b.Tools > 0 && s.Count > b.Tools {
		over = append(over, fmt.Sprintf("%d tools, and the budget allows %d", s.Count, b.Tools))
	}
	if b.Description > 0 {
		for _, t := range s.Tools {
			if t.Description > b.Description {
				over = append(over, fmt.Sprintf("tool %s's description takes %d bytes, and the budget allows %d", t.Name, t.Description, b.Description))
			}
		}
	}
	if b.Total > 0 && s.Total > b.Total {
		over = append(over, fmt.Sprintf("the list takes %d bytes, and the budget allows %d", s.Total, b.Total))
	}
	return over
}

// Table is the surface as a Markdown table: one row per tool in order, then
// the sum.
func (s Surface) Table() string {
	var b strings.Builder
	b.WriteString("| # | tool | description bytes | description characters | served bytes |\n|---|---|---|---|---|\n")
	descriptions := 0
	for i, t := range s.Tools {
		fmt.Fprintf(&b, "| %d | `%s` | %d | %d | %d |\n", i+1, t.Name, t.Description, t.Runes, t.Served)
		descriptions += t.Description
	}
	fmt.Fprintf(&b, "| | %d tools | %d | | %d |\n", s.Count, descriptions, s.Total)
	return b.String()
}
