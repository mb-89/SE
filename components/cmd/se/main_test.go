package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
	"github.com/mb-89/se/components/fleet"
	"github.com/mb-89/se/components/origin"
	"github.com/mb-89/se/components/retro"
)

// toolUse is a PostToolUse payload as a cloud session's hook hands it, with
// the GitHub tool's answer as its text.
func toolUse(tool string, input map[string]any, answer any) []byte {
	text, _ := json.Marshal(answer)
	quoted, _ := json.Marshal(string(text))
	in, _ := json.Marshal(input)
	return []byte(fmt.Sprintf(`{"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": %q, "tool_input": %s,
		"tool_use_id": "toolu_1", "tool_response": [{"type": "text", "text": %s}]}`, tool, in, quoted))
}

// SE's wiring starts with kern's GitHub component and SE's own, and through
// the real core a session's GitHub tool answers land as snapshots, from
// which fleet/findings and retro/due derive at once, read by a client.
func TestSEsWiringDerivesTheFleetAndTheRetroFromTheNames(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "wiring.toml"))
	if err != nil {
		t.Fatal(err)
	}
	w, err := index.ParseWiring(data)
	if err != nil {
		t.Fatal(err)
	}
	origin.Read = func(string) (map[string]time.Time, error) {
		return map[string]time.Time{"main": time.Now()}, nil
	}
	g := github.New(github.Options{Token: func() (string, error) { return "", nil }})
	c, err := host.Serve(host.Options{Root: t.TempDir(), Wiring: w,
		Components: []*index.Component{g.Component, origin.Component, fleet.Component, retro.Component}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Stop("the case ends"); <-c.Ended() })
	s, _ := c.Standing()
	post := func(n int, answer map[string]any) {
		t.Helper()
		in := map[string]any{"method": "get", "owner": "mb-89", "repo": "SE", "issue_number": n}
		if _, err := host.Post(host.Wall{}, s.Root, "PostToolUse", toolUse("mcp__github__issue_read", in, answer), 10*time.Second); err != nil {
			t.Fatal(err)
		}
	}
	post(1, map[string]any{"number": 1, "title": "feat/a", "state": "open", "labels": []string{"work", "in-progress"}})
	post(2, map[string]any{"number": 2, "title": "decide", "state": "open", "labels": []string{"se-person"}})
	post(3, map[string]any{"number": 3, "title": "feat/c", "state": "open", "body": "## Blocked by\n\n#2\n"})

	nc, err := bus.Dial(s.Bus, bus.Client, s.Users[bus.Client])
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	get := func(name string, v any) {
		t.Helper()
		m, err := nc.Request(bus.Get+bus.Subject(name), nil, 10*time.Second)
		if err != nil {
			t.Fatal(err)
		}
		var got struct {
			Value    json.RawMessage `json:"value"`
			Provided bool            `json:"provided"`
			Error    string          `json:"error"`
		}
		if err := json.Unmarshal(m.Data, &got); err != nil || got.Error != "" || !got.Provided {
			t.Fatalf("get %s answers %s, and wants a provided value", name, m.Data)
		}
		if err := json.Unmarshal(got.Value, v); err != nil {
			t.Fatal(err)
		}
	}
	var found fleet.Findings
	get("fleet/findings", &found)
	kinds := map[string]int{}
	for _, f := range found.Findings {
		kinds[f.Kind] = f.Issue
	}
	if found.Issues != 3 || found.Branches != 1 || kinds["no branch"] != 1 || kinds["waiting on the person"] != 2 {
		t.Fatalf("fleet/findings is %+v, and wants 3 issues read, #1 without a branch, #2 waiting on the person", found)
	}
	var due retro.Due
	get("retro/due", &due)
	if due.Issues != 3 || due.Landed != 0 || due.Due || due.DueAfter != 10 {
		t.Fatalf("retro/due is %+v, and wants 3 issues read, none landed, due after 10", due)
	}
}
