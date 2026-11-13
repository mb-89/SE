package github

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// PostToolUse is the host's event that carries a tool's answer.
const PostToolUse = "PostToolUse"

// readRelay answers a snapshot younger than refresh at once. Otherwise it
// puts the read's step in the outbox and waits up to relay-wait for the
// session's tool answer, which hear matches to it; without one in time it
// fails, naming the step, and the step stays until an answer lands.
func (g *GitHub) readRelay(k kind, r Ref) (Snapshot, error) {
	ob := outboxKey(k, r)
	now := g.o.Now()
	g.mu.Lock()
	if s, ok := g.last[ob]; ok && now.Sub(s.Read) < g.fresh {
		g.mu.Unlock()
		return s, nil
	}
	step := stepOf(k, r, now)
	wait, commit, fresh := g.wait, g.commit, !g.outbox[ob]
	g.outbox[ob] = true
	answer := make(chan Snapshot, 1)
	g.waiting[ob] = append(g.waiting[ob], answer)
	g.mu.Unlock()
	if fresh {
		if err := commit(outboxOut.At(ob, step)); err != nil {
			return Snapshot{}, err
		}
	}
	timer := time.NewTimer(wait)
	defer timer.Stop()
	select {
	case s := <-answer:
		return s, nil
	case <-timer.C:
	}
	in, _ := json.Marshal(step.Input)
	return Snapshot{}, fmt.Errorf("github %s %s: asked through the relay: run the GitHub tool %s with %s; outbox step %s", k.verb, Key(r), step.Tool, in, ob)
}

// stepOf is the tool call that reads r in a session.
func stepOf(k kind, r Ref, asked time.Time) Step {
	return Step{Tool: k.tool, Asked: asked.UTC(), Input: map[string]any{
		"method": k.method, "owner": r.Owner, "repo": r.Repo, k.numberArg: r.Number,
	}}
}

// toolUse is the part of a PostToolUse payload the relay reads.
type toolUse struct {
	Tool     string          `json:"tool_name"`
	Input    map[string]any  `json:"tool_input"`
	Response json.RawMessage `json:"tool_response"`
}

// hear reads every GitHub tool answer a session receives: a read of an
// issue, a pull request or a pull request's check runs lands in its snapshot
// with the time it was heard, and answers the outbox step that asked it. Any
// other event or tool passes unread.
func (g *GitHub) hear(instance, event string, payload []byte) error {
	if event != PostToolUse {
		return nil
	}
	var use toolUse
	if err := json.Unmarshal(payload, &use); err != nil {
		return nil // not a tool use the relay reads
	}
	k, r, ok := match(use)
	if !ok {
		return nil
	}
	data, err := answerOf(use.Response)
	if err != nil {
		return fmt.Errorf("github: %s for %s: %w", use.Tool, Key(r), err)
	}
	return g.land(k, r, Snapshot{Repo: repoOf(r), Number: r.Number, Read: g.o.Now().UTC(), Via: Relay, Data: data})
}

// match answers the read a tool use is: an MCP tool whose bare name, after
// its server's prefix, and method are a kind's, with an owner, a repository
// and a number.
func match(use toolUse) (kind, Ref, bool) {
	if !strings.HasPrefix(use.Tool, "mcp__") {
		return kind{}, Ref{}, false
	}
	bare := use.Tool[strings.LastIndex(use.Tool, "__")+2:]
	method, _ := use.Input["method"].(string)
	owner, _ := use.Input["owner"].(string)
	repo, _ := use.Input["repo"].(string)
	for _, k := range kinds {
		if k.tool != bare || k.method != method {
			continue
		}
		n, ok := number(use.Input[k.numberArg])
		if !ok || owner == "" || repo == "" {
			return kind{}, Ref{}, false
		}
		return k, Ref{Owner: owner, Repo: repo, Number: n}, true
	}
	return kind{}, Ref{}, false
}

// number reads a tool input's number, which JSON hands as a float or a string.
func number(v any) (int, bool) {
	switch n := v.(type) {
	case float64:
		return int(n), n > 0 && n == float64(int(n))
	case string:
		var i int
		_, err := fmt.Sscanf(n, "%d", &i)
		return i, err == nil && i > 0
	}
	return 0, false
}

// answerOf reads a tool's answer: MCP content, a list of {"type": "text",
// "text": <JSON>} or an object holding it under content, or the JSON text
// itself. An answer that is no JSON, or an error, is refused.
func answerOf(raw json.RawMessage) (any, error) {
	var blocks []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	var wrapped struct {
		Content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		} `json:"content"`
		IsError bool `json:"isError"`
	}
	var text string
	switch {
	case json.Unmarshal(raw, &blocks) == nil && len(blocks) > 0:
		text = blocks[0].Text
	case json.Unmarshal(raw, &wrapped) == nil && len(wrapped.Content) > 0:
		if wrapped.IsError {
			return nil, fmt.Errorf("the tool answered an error: %.200s", wrapped.Content[0].Text)
		}
		text = wrapped.Content[0].Text
	case json.Unmarshal(raw, &text) == nil:
	default:
		return nil, fmt.Errorf("the answer is no MCP content")
	}
	var data any
	if err := json.Unmarshal([]byte(text), &data); err != nil {
		return nil, fmt.Errorf("the answer is no JSON: %.200s", text)
	}
	return data, nil
}
