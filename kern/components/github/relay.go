package github

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/mb-89/kern/index"
)

// PostToolUse is the host's event that carries a tool's answer.
const PostToolUse = "PostToolUse"

// ask answers a relay read: a snapshot or list younger than refresh at
// once. Otherwise it puts the read's step in the outbox and waits up to
// relay-wait for the session's tool answer, which hear matches to it; without
// one in time it fails, naming the step the outbox holds then (a paged
// read's next page), and the step stays until an answer lands.
func (g *GitHub) ask(verb, key, ob string, step Step) (any, error) {
	now := g.o.Now()
	g.mu.Lock()
	if v, ok := g.last[ob]; ok && now.Sub(readOf(v)) < g.fresh {
		g.mu.Unlock()
		return v, nil
	}
	wait, commit := g.wait, g.commit
	_, open := g.outbox[ob]
	if !open {
		g.outbox[ob] = step
	}
	answer := make(chan any, 1)
	g.waiting[ob] = append(g.waiting[ob], answer)
	g.mu.Unlock()
	if !open {
		if err := commit(outboxOut.At(ob, step)); err != nil {
			return nil, err
		}
	}
	timer := time.NewTimer(wait)
	defer timer.Stop()
	select {
	case v := <-answer:
		return v, nil
	case <-timer.C:
	}
	g.mu.Lock()
	if s, ok := g.outbox[ob]; ok {
		step = s
	}
	g.mu.Unlock()
	in, _ := json.Marshal(step.Input)
	return nil, fmt.Errorf("github %s %s: asked through the relay: run the GitHub tool %s with %s; outbox step %s", verb, key, step.Tool, in, ob)
}

// readOf is the time a snapshot or a list was read.
func readOf(v any) time.Time {
	switch s := v.(type) {
	case Snapshot:
		return s.Read
	case List:
		return s.Read
	}
	return time.Time{}
}

// stepOf is the tool call that reads r in a session; a paged kind's asks
// its first page.
func stepOf(k kind, r Ref, asked time.Time) Step {
	in := map[string]any{"method": k.method, "owner": r.Owner, "repo": r.Repo, k.numberArg: r.Number}
	if k.paged {
		in["perPage"] = perPage
	}
	return Step{Tool: k.tool, Asked: asked.UTC(), Input: in}
}

// pages is a paged relay read under way: the items of the pages heard so
// far and the page the outbox asks next.
type pages struct {
	items []any
	next  map[string]any
}

// pageOf reads one page of a tool's list answer: list_issues answers
// {"issues": [...], "pageInfo": {"hasNextPage", "endCursor"}}, and its next
// page is asked with after; the other list tools answer the bare items, and
// a page as long as the call's perPage (30 where it names none) has a next,
// asked with page.
func pageOf(data any, input map[string]any) ([]any, map[string]any, error) {
	switch d := data.(type) {
	case []any:
		size, ok := number(input["perPage"])
		if !ok {
			size = toolPerPage
		}
		if len(d) < size {
			return d, nil, nil
		}
		page, ok := number(input["page"])
		if !ok {
			page = 1
		}
		return d, map[string]any{"page": page + 1}, nil
	case map[string]any:
		items, ok := d["issues"].([]any)
		if !ok {
			return nil, nil, fmt.Errorf("the answer holds no list of issues")
		}
		info, _ := d["pageInfo"].(map[string]any)
		if more, _ := info["hasNextPage"].(bool); more {
			cursor, _ := info["endCursor"].(string)
			if cursor == "" {
				return nil, nil, fmt.Errorf("the answer has a next page and names no endCursor")
			}
			return items, map[string]any{"after": cursor}, nil
		}
		return items, nil, nil
	}
	return nil, nil, fmt.Errorf("the answer is no list")
}

// first says whether a tool call asks a list's first page.
func first(input map[string]any) bool {
	if _, ok := input["after"]; ok {
		return false
	}
	page, ok := number(input["page"])
	return !ok || page == 1
}

// follows says whether a tool call asks the page a read under way waits for.
func follows(input, next map[string]any) bool {
	if c, ok := next["after"]; ok {
		return input["after"] == c
	}
	page, _ := number(input["page"])
	want, _ := next["page"].(int)
	return page == want
}

// hearPage takes one page of a paged read. A first page starts the read
// afresh; a later page counts only where it is the page the outbox asks.
// The last page lands the whole read; a page with a next one behind it puts
// that page's step in the outbox, where the read was asked. A first page
// nobody asked, with more behind it, lands nothing: it is no whole list.
func (g *GitHub) hearPage(ob string, input map[string]any, data any, step func(next map[string]any) Step, whole func(items []any) (index.Write, any)) error {
	items, next, err := pageOf(data, input)
	if err != nil {
		return err
	}
	g.mu.Lock()
	_, asked := g.outbox[ob]
	p := g.pages[ob]
	switch {
	case first(input):
		p = &pages{}
	case p == nil || !follows(input, p.next):
		g.mu.Unlock()
		return nil // a page of no read under way
	}
	p.items = append(p.items, items...)
	if next != nil {
		if !asked {
			g.mu.Unlock()
			return nil
		}
		p.next = next
		g.pages[ob] = p
		s := step(next)
		g.outbox[ob] = s
		commit := g.commit
		g.mu.Unlock()
		return commit(outboxOut.At(ob, s))
	}
	g.mu.Unlock()
	w, v := whole(p.items)
	return g.land(ob, w, v)
}

// toolUse is the part of a PostToolUse payload the relay reads.
type toolUse struct {
	Tool     string          `json:"tool_name"`
	Input    map[string]any  `json:"tool_input"`
	Response json.RawMessage `json:"tool_response"`
}

// hear reads every GitHub tool answer a session receives: a read of an
// issue, a pull request, its check runs or its comments, or a list of a
// repository's issues or pull requests, lands in its name with the time it
// was heard, and answers the outbox step that asked it; a paged read lands
// once its last page is heard. Any other event or tool passes unread.
func (g *GitHub) hear(instance, event string, payload []byte) error {
	if event != PostToolUse {
		return nil
	}
	var use toolUse
	if err := json.Unmarshal(payload, &use); err != nil || !strings.HasPrefix(use.Tool, "mcp__") {
		return nil // not a tool use the relay reads
	}
	bare := use.Tool[strings.LastIndex(use.Tool, "__")+2:]
	if l, r, ok := matchList(use, bare); ok {
		data, err := answerOf(use.Response)
		if err == nil {
			err = g.hearPage(listOutboxKey(l, r), use.Input, data,
				func(next map[string]any) Step { return listStepOf(l, r, g.o.Now(), next) },
				func(items []any) (index.Write, any) {
					list := List{Repo: repoOf(r.Owner, r.Repo), State: r.State, Labels: r.Labels, Read: g.o.Now().UTC(), Via: Relay, Data: items}
					return l.out().At(ListKey(r), list), list
				})
		}
		if err != nil {
			return fmt.Errorf("github: %s for %s: %w", use.Tool, ListKey(r), err)
		}
		return nil
	}
	k, r, ok := match(use, bare)
	if !ok {
		return nil
	}
	data, err := answerOf(use.Response)
	if err == nil && k.paged {
		err = g.hearPage(outboxKey(k, r), use.Input, data,
			func(next map[string]any) Step {
				s := stepOf(k, r, g.o.Now())
				for n, v := range next {
					s.Input[n] = v
				}
				return s
			},
			func(items []any) (index.Write, any) {
				s := Snapshot{Repo: repoOf(r.Owner, r.Repo), Number: r.Number, Read: g.o.Now().UTC(), Via: Relay, Data: items}
				return k.out().At(Key(r), s), s
			})
	} else if err == nil {
		s := Snapshot{Repo: repoOf(r.Owner, r.Repo), Number: r.Number, Read: g.o.Now().UTC(), Via: Relay, Data: data}
		err = g.land(outboxKey(k, r), k.out().At(Key(r), s), s)
	}
	if err != nil {
		return fmt.Errorf("github: %s for %s: %w", use.Tool, Key(r), err)
	}
	return nil
}

// match answers the read a tool use is: an MCP tool whose bare name, after
// its server's prefix, and method are a heard kind's, with an owner, a
// repository and a number.
func match(use toolUse, bare string) (kind, Ref, bool) {
	method, _ := use.Input["method"].(string)
	owner, _ := use.Input["owner"].(string)
	repo, _ := use.Input["repo"].(string)
	for _, k := range heard {
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
	case int:
		return n, n > 0
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
