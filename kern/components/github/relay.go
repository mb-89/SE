package github

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
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
	if g.answerStep(use) {
		g.mu.Lock()
		g.answered[string(payload)] = true
		g.mu.Unlock()
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

// The named JSON shapes of the verb step's request and answer, so a component
// in another language asks it: a declared request port of type github.step
// that answers github.step-answer binds to it.
const (
	StepShape       = "github.step"
	StepAnswerShape = "github.step-answer"
)

// StepAsk is what the verb step asks: one GitHub tool call the session runs,
// by the tool's bare name and its input, what the agent watches for, the
// input keys an answer must carry equal, and how long to wait for it.
type StepAsk struct {
	Tool  string         `json:"tool"`
	Input map[string]any `json:"input"`
	Note  string         `json:"note,omitempty"`
	// Match names the input keys a tool use must carry with the asked values;
	// empty, every asked key whose value is no text over MatchTextMax bytes.
	Match []string `json:"match,omitempty"`
	// Wait is how long the step waits, a duration such as 30m, up to
	// step-wait; empty, step-wait.
	Wait string `json:"wait,omitempty"`
}

// StepAnswer is what the verb step answers: the tool use that answered the
// step, its input as the session sent it, and its answer, read as JSON where
// it is JSON and as its text where it is not.
type StepAnswer struct {
	Tool  string         `json:"tool"`
	Input map[string]any `json:"input"`
	Read  time.Time      `json:"read"`
	Data  any            `json:"data"`
}

// MatchTextMax is the longest text an asked input key carries and still
// takes part in the match by default: a body or a message the session copies
// may differ in a byte, so the asker reads it back from the answer's input.
const MatchTextMax = 200

type waitingStep struct {
	ask    StepAsk
	asked  time.Time
	answer chan stepResult
}

type stepResult struct {
	a   StepAnswer
	err error
}

// StepKey is a step's key in the outbox: step.<tool>.<hash of its input>, so
// one tool call asked twice waits as one entry.
func StepKey(a StepAsk) string {
	data, _ := json.Marshal(a.Input) // maps marshal in key order
	sum := sha256.Sum256(append([]byte(a.Tool+"\n"), data...))
	return "step." + strings.ToLower(a.Tool) + "." + hex.EncodeToString(sum[:6])
}

// step puts one tool call in the outbox and waits for the PostToolUse that
// answers it, its wait, or ctx: once the call that asked it is given up, the
// step leaves the outbox at once, so no session is pointed at a step no one
// waits for. Only the relay runs steps: with a token, the application runs
// its GitHub steps itself.
func (g *GitHub) step(ctx context.Context, a StepAsk) (StepAnswer, error) {
	if a.Tool == "" || strings.Contains(a.Tool, "__") || a.Input == nil {
		return StepAnswer{}, fmt.Errorf("github step: a step names the tool's bare name, such as merge_pull_request, and its input, not %+v", a)
	}
	g.mu.Lock()
	backend, commit, max := g.backend, g.commit, g.stepWait
	g.mu.Unlock()
	if backend != Relay {
		return StepAnswer{}, fmt.Errorf("github step %s: the backend is %q: only the relay runs a session's tool calls", a.Tool, backend)
	}
	wait := max
	if a.Wait != "" {
		d, err := time.ParseDuration(a.Wait)
		if err != nil || d < 0 {
			return StepAnswer{}, fmt.Errorf("github step %s: wait %q is no duration, such as 30m", a.Tool, a.Wait)
		}
		if d < wait {
			wait = d
		}
	}
	key := StepKey(a)
	now := g.o.Now().UTC()
	w := &waitingStep{ask: a, asked: now, answer: make(chan stepResult, 1)}
	g.mu.Lock()
	if _, taken := g.steps[key]; taken {
		g.mu.Unlock()
		return StepAnswer{}, fmt.Errorf("github step %s: the same call already waits as outbox step %s", a.Tool, key)
	}
	g.steps[key] = w
	g.mu.Unlock()
	if err := commit(outboxOut.At(key, Step{Tool: a.Tool, Input: a.Input, Asked: now, Note: a.Note})); err != nil {
		g.drop(key)
		return StepAnswer{}, err
	}
	select {
	case g.asked <- struct{}{}:
	default:
	}
	timer := time.NewTimer(wait)
	defer timer.Stop()
	select {
	case r := <-w.answer:
		return r.a, r.err
	case <-ctx.Done():
		g.drop(key)
		return StepAnswer{}, fmt.Errorf("github step %s: its call is given up: %w; outbox step %s dropped", a.Tool, context.Cause(ctx), key)
	case <-timer.C:
	}
	g.drop(key)
	in, _ := json.Marshal(a.Input)
	return StepAnswer{}, fmt.Errorf("github step %s: no tool answer within %v: run the GitHub tool %s with %s; outbox step %s", a.Tool, wait, a.Tool, in, key)
}

// drop takes a step out of the outbox, answered or given up.
func (g *GitHub) drop(key string) {
	g.mu.Lock()
	delete(g.steps, key)
	commit := g.commit
	g.mu.Unlock()
	if commit != nil {
		_ = commit(outboxOut.Drop(key))
	}
}

// answerStep answers the oldest waiting step a tool use matches, and says
// whether one was.
func (g *GitHub) answerStep(use toolUse) bool {
	if !strings.HasPrefix(use.Tool, "mcp__") {
		return false
	}
	bare := use.Tool[strings.LastIndex(use.Tool, "__")+2:]
	g.mu.Lock()
	var key string
	var w *waitingStep
	for k, s := range g.steps {
		if s.ask.Tool == bare && matches(s.ask, use.Input) && (w == nil || k < key) {
			key, w = k, s
		}
	}
	g.mu.Unlock()
	if w == nil {
		return false
	}
	data, err := stepAnswerOf(use.Response)
	select { // a step asked before this answer is no next step for its tell
	case <-g.asked:
	default:
	}
	g.drop(key)
	if err != nil {
		err = fmt.Errorf("github step %s: %w", bare, err)
	}
	w.answer <- stepResult{StepAnswer{Tool: bare, Input: use.Input, Read: g.o.Now().UTC(), Data: data}, err}
	return true
}

// matches says whether a tool use's input carries every key the step matches
// on with the asked value; numbers compare as numbers, a number and its
// decimal text alike, and owner and repo regardless of case.
func matches(a StepAsk, input map[string]any) bool {
	keys := a.Match
	if len(keys) == 0 {
		for k, v := range a.Input {
			if s, long := v.(string); !long || len(s) <= MatchTextMax {
				keys = append(keys, k)
			}
		}
	}
	for _, k := range keys {
		want, asked := a.Input[k]
		got, sent := input[k]
		if !asked || !sent || !same(k, want, got) {
			return false
		}
	}
	return true
}

// same compares an asked value with a sent one; owner and repo regardless of
// case, as GitHub reads them.
func same(key string, a, b any) bool {
	if x, ok := a.(string); ok && (key == "owner" || key == "repo") {
		y, ok := b.(string)
		return ok && strings.EqualFold(x, y)
	}
	if n, ok := number(a); ok {
		m, ok := number(b)
		return ok && n == m
	}
	x, _ := json.Marshal(a)
	y, _ := json.Marshal(b)
	return string(x) == string(y)
}

// stepAnswerOf reads a step's answer as answerOf does, and keeps a text that
// is no JSON, as a write tool may answer, as that text.
func stepAnswerOf(raw json.RawMessage) (any, error) {
	data, err := answerOf(raw)
	if err == nil {
		return data, nil
	}
	var blocks []struct {
		Text string `json:"text"`
	}
	var wrapped struct {
		Content []struct {
			Text string `json:"text"`
		} `json:"content"`
		IsError bool `json:"isError"`
	}
	switch {
	case json.Unmarshal(raw, &blocks) == nil && len(blocks) > 0:
		return blocks[0].Text, nil
	case json.Unmarshal(raw, &wrapped) == nil && len(wrapped.Content) > 0 && !wrapped.IsError:
		return wrapped.Content[0].Text, nil
	}
	var text string
	if json.Unmarshal(raw, &text) == nil {
		return text, nil
	}
	return nil, err
}

// tell answers what the relay waits for, on the events whose hook hands the
// agent context: every outbox entry, oldest first, as the tool call to run.
// Where this event's tool answer answered a step, it first waits up to
// tell-wait for the next step to be asked, so the agent is told that one.
func (g *GitHub) tell(_ string, event string, payload []byte) string {
	if event != PostToolUse && event != "UserPromptSubmit" && event != "SessionStart" {
		return ""
	}
	g.mu.Lock()
	answered := g.answered[string(payload)]
	delete(g.answered, string(payload))
	wait := g.tellWait
	g.mu.Unlock()
	if answered {
		timer := time.NewTimer(wait)
		select {
		case <-g.asked:
		case <-timer.C:
		}
		timer.Stop()
	}
	return g.Outbox()
}

// Outbox is the relay's waiting tool calls as the agent is told them, oldest
// first, or "" where none waits.
func (g *GitHub) Outbox() string {
	g.mu.Lock()
	type entry struct {
		key  string
		step Step
	}
	var all []entry
	for key, w := range g.steps {
		all = append(all, entry{key, Step{Tool: w.ask.Tool, Input: w.ask.Input, Asked: w.asked, Note: w.ask.Note}})
	}
	for key, step := range g.outbox {
		all = append(all, entry{key, step})
	}
	g.mu.Unlock()
	if len(all) == 0 {
		return ""
	}
	sort.Slice(all, func(i, j int) bool {
		if !all[i].step.Asked.Equal(all[j].step.Asked) {
			return all[i].step.Asked.Before(all[j].step.Asked)
		}
		return all[i].key < all[j].key
	})
	lines := []string{"kern's GitHub relay waits for these GitHub tool calls; run each with exactly this input (its answer reaches kern through the PostToolUse hook):"}
	for i, e := range all {
		in, _ := json.Marshal(e.step.Input)
		line := fmt.Sprintf("%d. %s %s", i+1, e.step.Tool, in)
		if e.step.Note != "" {
			line += "\n   " + e.step.Note
		}
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n")
}
