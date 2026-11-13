package github

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
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
	if fresh {
		g.asking[ob] = step
	}
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
	if g.answerStep(use) {
		g.mu.Lock()
		g.answered[string(payload)] = true
		g.mu.Unlock()
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

// stepKey is a step's key in the outbox: step.<tool>.<hash of its input>, so
// one tool call asked twice waits as one entry.
func stepKey(a StepAsk) string {
	data, _ := json.Marshal(a.Input) // maps marshal in key order
	sum := sha256.Sum256(append([]byte(a.Tool+"\n"), data...))
	return "step." + strings.ToLower(a.Tool) + "." + hex.EncodeToString(sum[:6])
}

// step puts one tool call in the outbox and waits for the PostToolUse that
// answers it. Only the relay runs steps: with a token, the application runs
// its GitHub steps itself.
func (g *GitHub) step(a StepAsk) (StepAnswer, error) {
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
	key := stepKey(a)
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
	for key := range g.outbox {
		all = append(all, entry{key, g.asking[key]})
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
