package template

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

// Command discovery for the rule dangling: the subcommands a script's argument parser defines, as
// scripts/references.py `command_tree` gives them (its argparse parser, captured where `main([])`
// first parses). Python reads the parser by running the script; Go reads the script's source: the
// parser `main` parses (argparse's, or se_script.parser's), its `add_subparsers` and `add_parser`
// calls, nested, and where it has none, its first positional's `choices`, through the variables, the
// module's constants, the `for` loops and the functions `main` calls; work_tickets.py's registry (`command_group` and the `@command`
// decorators with their `parent=`) as its `build_parser` lays it out. The agreement test
// (components/agreement) holds this reading to Python's tree for every script of SE's checkout.

// Tree is a parser's subcommands, nested; empty where it defines none.
type Tree map[string]Tree

// Names are the tree's subcommands, sorted as Python sorts them.
func (t Tree) Names() []string { return sortedKeys(t) }

type treeKey struct {
	path string
	size int64
	mod  int64
}

var trees = struct {
	mu   sync.Mutex
	read map[treeKey]Tree
}{read: map[treeKey]Tree{}}

// CommandTree is the tree of the script at path: empty where it is no `.py` file, does not hold
// "argparse" or has no `main` that parses. It is read once per version of the file.
func CommandTree(path string) Tree {
	info, err := os.Stat(path)
	if err != nil || info.IsDir() || filepath.Ext(path) != ".py" {
		return Tree{}
	}
	key := treeKey{path, info.Size(), info.ModTime().UnixNano()}
	trees.mu.Lock()
	found, ok := trees.read[key]
	trees.mu.Unlock()
	if ok {
		return found
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return Tree{}
	}
	found = ScriptTree(string(data))
	trees.mu.Lock()
	trees.read[key] = found
	trees.mu.Unlock()
	return found
}

// ScriptTree is the tree of a script's source text.
func ScriptTree(source string) Tree {
	if !strings.Contains(source, "argparse") && !strings.Contains(source, "se_script") {
		return Tree{}
	}
	m := readModule(source)
	if _, ok := m.functions["main"]; !ok {
		return Tree{}
	}
	if m.registry() {
		return m.registryTree()
	}
	root := m.captured()
	if root == nil {
		return Tree{}
	}
	return root.tree()
}

// Tokens and statements: the little of Python's grammar the reading needs.

type token struct {
	kind  byte // 'n' name, 's' string, '0' number, 'o' operator or bracket
	text  string
	value string // a string's value
	plain bool   // a string with no f prefix: its value is its text
}

type statement struct {
	indent int
	tokens []token
}

func isNameStart(r byte) bool {
	return r == '_' || r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || r >= 0x80
}
func isNameChar(r byte) bool { return isNameStart(r) || r >= '0' && r <= '9' }

// statements splits Python source into its logical lines, each with the column it starts at.
func statements(src string) []statement {
	var found []statement
	var current []token
	indent, depth, lineStart := 0, 0, true
	flush := func() {
		if len(current) > 0 {
			found = append(found, statement{indent, current})
		}
		current, lineStart = nil, true
	}
	for i := 0; i < len(src); {
		c := src[i]
		switch {
		case c == '\n':
			if depth == 0 {
				flush()
			}
			i++
			continue
		case c == ' ' || c == '\t' || c == '\r' || c == '\f':
			i++
			continue
		case c == '\\' && i+1 < len(src) && (src[i+1] == '\n' || src[i+1] == '\r'):
			i += 2
			continue
		case c == '#':
			for i < len(src) && src[i] != '\n' {
				i++
			}
			continue
		}
		if lineStart && depth == 0 {
			start := strings.LastIndexByte(src[:i], '\n') + 1
			indent = len(strings.ReplaceAll(src[start:i], "\t", "        "))
			lineStart = false
		}
		switch {
		case isNameStart(c):
			j := i
			for j < len(src) && isNameChar(src[j]) {
				j++
			}
			if j < len(src) && (src[j] == '\'' || src[j] == '"') && j-i <= 3 && strings.Trim(strings.ToLower(src[i:j]), "rbuf") == "" {
				tok, end := readString(src, i, j)
				current = append(current, tok)
				i = end
				continue
			}
			current = append(current, token{kind: 'n', text: src[i:j]})
			i = j
		case c == '\'' || c == '"':
			tok, end := readString(src, i, i)
			current = append(current, tok)
			i = end
		case c >= '0' && c <= '9' || c == '.' && i+1 < len(src) && src[i+1] >= '0' && src[i+1] <= '9':
			j := i
			for j < len(src) && (isNameChar(src[j]) || src[j] == '.') {
				j++
			}
			current = append(current, token{kind: '0', text: src[i:j]})
			i = j
		default:
			op := string(c)
			if i+1 < len(src) && strings.Contains("=!<>*/+-%&|^:@", string(c)) && (src[i+1] == '=' || c == '*' && src[i+1] == '*' || c == '-' && src[i+1] == '>' || c == '/' && src[i+1] == '/') {
				op = src[i : i+2]
			}
			switch op {
			case "(", "[", "{":
				depth++
			case ")", "]", "}":
				if depth > 0 {
					depth--
				}
			}
			current = append(current, token{kind: 'o', text: op})
			i += len(op)
		}
	}
	flush()
	return found
}

// readString reads the string literal whose prefix starts at i and whose quote is at q.
func readString(src string, i, q int) (token, int) {
	prefix := strings.ToLower(src[i:q])
	raw, formatted := strings.Contains(prefix, "r"), strings.Contains(prefix, "f")
	quote := src[q : q+1]
	if strings.HasPrefix(src[q:], strings.Repeat(quote, 3)) {
		quote = strings.Repeat(quote, 3)
	}
	var b strings.Builder
	j := q + len(quote)
	for j < len(src) {
		if strings.HasPrefix(src[j:], quote) {
			j += len(quote)
			break
		}
		if src[j] == '\\' && j+1 < len(src) {
			if raw {
				b.WriteString(src[j : j+2])
			} else {
				switch src[j+1] {
				case 'n':
					b.WriteByte('\n')
				case 't':
					b.WriteByte('\t')
				case '\n':
				default:
					b.WriteByte(src[j+1])
				}
			}
			j += 2
			continue
		}
		if len(quote) == 1 && src[j] == '\n' {
			break
		}
		b.WriteByte(src[j])
		j++
	}
	return token{kind: 's', text: src[i:j], value: b.String(), plain: !formatted}, j
}

// Expressions: an atom with its trailers, where the brackets' items are split at their commas.

type expr struct {
	kind   string // name, str, num, tuple, list, set, dict, attr, call, index, other
	text   string
	items  []*expr // a tuple's, list's or set's items; a dict's keys; a call's positionals
	kw     map[string]*expr
	of     *expr // what an attribute, a call or a subscript applies to
	plain  bool
	fixed  bool // a string: every part is a plain literal
	strung bool
}

// closing is the index of the bracket that closes the one at i.
func closing(tokens []token, i int) int {
	depth := 0
	for j := i; j < len(tokens); j++ {
		if tokens[j].kind != 'o' {
			continue
		}
		switch tokens[j].text {
		case "(", "[", "{":
			depth++
		case ")", "]", "}":
			depth--
			if depth == 0 {
				return j
			}
		}
	}
	return len(tokens)
}

// splitTop splits tokens at the commas outside their brackets; an empty last part is dropped.
func splitTop(tokens []token, sep string) [][]token {
	var parts [][]token
	start, depth := 0, 0
	for j, tok := range tokens {
		if tok.kind != 'o' {
			continue
		}
		switch tok.text {
		case "(", "[", "{":
			depth++
		case ")", "]", "}":
			depth--
		case sep:
			if depth == 0 {
				parts = append(parts, tokens[start:j])
				start = j + 1
			}
		}
	}
	if start < len(tokens) {
		parts = append(parts, tokens[start:])
	}
	return parts
}

func isOp(tok token, text string) bool { return tok.kind == 'o' && tok.text == text }

// parseExpr reads the primary that opens tokens: what follows it (an operator) is not read.
func parseExpr(tokens []token) *expr {
	if len(tokens) == 0 {
		return &expr{kind: "other"}
	}
	var e *expr
	i := 0
	tok := tokens[0]
	switch {
	case tok.kind == 'n' && tok.text == "lambda":
		return &expr{kind: "other"}
	case tok.kind == 'n':
		e, i = &expr{kind: "name", text: tok.text}, 1
	case tok.kind == 's':
		e = &expr{kind: "str", fixed: true}
		var b strings.Builder
		for i < len(tokens) && tokens[i].kind == 's' {
			b.WriteString(tokens[i].value)
			e.fixed = e.fixed && tokens[i].plain
			i++
		}
		e.text = b.String()
	case tok.kind == '0':
		e, i = &expr{kind: "num", text: tok.text}, 1
	case isOp(tok, "(") || isOp(tok, "[") || isOp(tok, "{"):
		end := closing(tokens, 0)
		inner := tokens[1:min(end, len(tokens))]
		kind := map[string]string{"(": "tuple", "[": "list", "{": "set"}[tok.text]
		e = &expr{kind: kind}
		for _, part := range splitTop(inner, ",") {
			if kind == "set" {
				if pair := splitTop(part, ":"); len(pair) > 1 || len(part) > 0 && isOp(part[len(part)-1], ":") {
					e.kind = "dict"
					part = pair[0]
				}
			}
			e.items = append(e.items, parseExpr(part))
		}
		if kind == "tuple" && len(e.items) == 1 && len(splitTop(inner, ",")) == 1 && !(len(inner) > 0 && isOp(inner[len(inner)-1], ",")) {
			e = e.items[0]
		}
		i = end + 1
	default:
		return &expr{kind: "other"}
	}
	for i < len(tokens) {
		tok := tokens[i]
		switch {
		case isOp(tok, ".") && i+1 < len(tokens) && tokens[i+1].kind == 'n':
			e = &expr{kind: "attr", text: tokens[i+1].text, of: e}
			i += 2
		case isOp(tok, "("):
			end := closing(tokens, i)
			call := &expr{kind: "call", of: e, kw: map[string]*expr{}}
			for _, part := range splitTop(tokens[i+1:min(end, len(tokens))], ",") {
				switch {
				case len(part) > 1 && part[0].kind == 'n' && isOp(part[1], "="):
					call.kw[part[0].text] = parseExpr(part[2:])
				case len(part) > 0 && (isOp(part[0], "*") || isOp(part[0], "**")):
				default:
					call.items = append(call.items, parseExpr(part))
				}
			}
			e, i = call, end+1
		case isOp(tok, "["):
			end := closing(tokens, i)
			e, i = &expr{kind: "index", of: e}, end+1
		default:
			return e
		}
	}
	return e
}

// The module: its constants and functions, and the reading of what `main` parses.

type function struct {
	params []string
	body   []statement
}

type module struct {
	stmts     []statement
	constants map[string][]token
	functions map[string]function
	depth     int
}

func readModule(source string) *module {
	m := &module{stmts: statements(source), constants: map[string][]token{}, functions: map[string]function{}}
	for i := 0; i < len(m.stmts); i++ {
		st := m.stmts[i]
		if st.indent != 0 {
			continue
		}
		toks := st.tokens
		if len(toks) > 2 && toks[0].kind == 'n' && (toks[0].text == "def" || toks[0].text == "async" && toks[1].text == "def") {
			at := 1
			if toks[0].text == "async" {
				at = 2
			}
			name := toks[at].text
			var params []string
			if at+1 < len(toks) && isOp(toks[at+1], "(") {
				end := closing(toks, at+1)
				for _, part := range splitTop(toks[at+2:min(end, len(toks))], ",") {
					if len(part) > 0 && part[0].kind == 'n' {
						params = append(params, part[0].text)
					}
				}
			}
			j := i + 1
			for j < len(m.stmts) && m.stmts[j].indent > 0 {
				j++
			}
			m.functions[name] = function{params, m.stmts[i+1 : j]}
			i = j - 1
			continue
		}
		if at := assignment(toks); at > 0 && toks[0].kind == 'n' {
			m.constants[toks[0].text] = toks[at+1:]
		}
	}
	return m
}

// assignment is the index of a statement's `=`, 0 where it assigns nothing.
func assignment(toks []token) int {
	depth := 0
	for j, tok := range toks {
		if tok.kind != 'o' {
			continue
		}
		switch tok.text {
		case "(", "[", "{":
			depth++
		case ")", "]", "}":
			depth--
		case "=":
			if depth == 0 {
				return j
			}
		}
	}
	return 0
}

// A value the reading follows: a parser, a parser's subparsers, a text, a list of texts.

type parserNode struct {
	children []string
	child    map[string]*parserNode
	sub      bool
	choices  []string
	chosen   bool
}

type subparsers struct{ parser *parserNode }

type texts []string

func newParser() *parserNode { return &parserNode{child: map[string]*parserNode{}} }

func (p *parserNode) tree() Tree {
	found := Tree{}
	if p.sub {
		for _, name := range p.children {
			found[name] = p.child[name].tree()
		}
		return found
	}
	for _, choice := range p.choices {
		found[choice] = Tree{}
	}
	return found
}

type capture struct{ parser *parserNode }

type scope struct {
	vars   map[string]any
	parent *scope
}

func (s *scope) get(name string) (any, bool) {
	for at := s; at != nil; at = at.parent {
		if v, ok := at.vars[name]; ok {
			return v, true
		}
	}
	return nil, false
}

// captured is the parser `main` parses first, nil where it parses none the reading follows.
func (m *module) captured() (found *parserNode) {
	defer func() {
		if r := recover(); r != nil {
			c, ok := r.(capture)
			if !ok {
				panic(r)
			}
			found = c.parser
		}
	}()
	m.call("main", nil)
	return nil
}

func (m *module) call(name string, args []any) any {
	fn, ok := m.functions[name]
	if !ok || m.depth > 20 {
		return nil
	}
	m.depth++
	defer func() { m.depth-- }()
	s := &scope{vars: map[string]any{}}
	for i, param := range fn.params {
		if i < len(args) {
			s.vars[param] = args[i]
		}
	}
	value, _ := m.run(fn.body, s)
	return value
}

// run runs a block's statements in order, each compound statement's body once (a `for` loop's once
// per item); it answers a `return`'s value.
func (m *module) run(block []statement, s *scope) (any, bool) {
	for i := 0; i < len(block); i++ {
		st := block[i]
		j := i + 1
		for j < len(block) && block[j].indent > st.indent {
			j++
		}
		body := block[i+1 : j]
		toks := st.tokens
		head := ""
		if toks[0].kind == 'n' {
			head = toks[0].text
		}
		switch {
		case head == "def" || head == "class" || head == "async" || isOp(toks[0], "@"):
			i = j - 1
			continue
		case head == "for":
			in := -1
			for k, tok := range toks {
				if tok.kind == 'n' && tok.text == "in" {
					in = k
					break
				}
			}
			colon := len(toks) - 1
			if in < 0 || !isOp(toks[colon], ":") {
				i = j - 1
				continue
			}
			target := toks[1]
			for _, item := range textsOf(m.eval(parseExpr(toks[in+1:colon]), s)) {
				inner := &scope{vars: map[string]any{target.text: item}, parent: s}
				if v, done := m.run(body, inner); done {
					return v, true
				}
			}
			i = j - 1
			continue
		case head == "return":
			return m.eval(parseExpr(toks[1:]), s), true
		case head == "if" || head == "elif" || head == "else" || head == "try" || head == "except" || head == "finally" || head == "with" || head == "while":
			if head == "with" || head == "if" || head == "elif" || head == "while" {
				m.eval(parseExpr(toks[1:]), s)
			}
			if v, done := m.run(body, s); done {
				return v, true
			}
			i = j - 1
			continue
		}
		if at := assignment(toks); at > 0 {
			value := m.eval(parseExpr(toks[at+1:]), s)
			if toks[0].kind == 'n' && at == 1 {
				s.vars[toks[0].text] = value
			}
			continue
		}
		m.eval(parseExpr(toks), s)
	}
	return nil, false
}

// textsOf is a value read as the texts it holds, nil where it holds none.
func textsOf(v any) []string {
	switch x := v.(type) {
	case texts:
		return x
	}
	return nil
}

func (m *module) constant(name string) any {
	toks, ok := m.constants[name]
	if !ok || m.depth > 20 {
		return nil
	}
	m.depth++
	defer func() { m.depth-- }()
	return m.eval(parseExpr(toks), &scope{vars: map[string]any{}})
}

func (m *module) eval(e *expr, s *scope) any {
	switch e.kind {
	case "name":
		if v, ok := s.get(e.text); ok {
			return v
		}
		return m.constant(e.text)
	case "str":
		if e.fixed {
			return e.text
		}
		return nil
	case "num":
		return e.text
	case "tuple", "list", "set", "dict":
		var found texts
		for _, item := range e.items {
			v := m.eval(item, s)
			if text, ok := v.(string); ok {
				found = append(found, text)
			}
		}
		if found == nil {
			found = texts{}
		}
		return found
	case "attr":
		return nil
	case "call":
		return m.callValue(e, s)
	}
	return nil
}

func (m *module) callValue(e *expr, s *scope) any {
	args := make([]any, len(e.items))
	for i, item := range e.items {
		args[i] = m.eval(item, s)
	}
	if e.of.kind == "name" {
		switch e.of.text {
		case "tuple", "list":
			if len(args) > 0 {
				return append(texts{}, textsOf(args[0])...)
			}
			return texts{}
		case "sorted":
			if len(args) > 0 {
				found := append(texts{}, textsOf(args[0])...)
				sort.Strings(found)
				return found
			}
		}
		if _, ok := m.functions[e.of.text]; ok {
			return m.call(e.of.text, args)
		}
		return nil
	}
	if e.of.kind != "attr" {
		return nil
	}
	method := e.of.text
	if e.of.of.kind == "name" && (method == "ArgumentParser" && e.of.of.text == "argparse" ||
		method == "parser" && e.of.of.text == "se_script") {
		return newParser() // argparse's, or the one se_script.parser makes (scripts/se_script.py)
	}
	receiver := m.eval(e.of.of, s)
	switch r := receiver.(type) {
	case *parserNode:
		switch method {
		case "parse_args", "parse_known_args":
			panic(capture{r})
		case "add_subparsers":
			if r.sub {
				return nil
			}
			r.sub = true
			return &subparsers{r}
		case "add_mutually_exclusive_group", "add_argument_group":
			return r
		case "add_argument":
			if len(args) == 0 || r.chosen {
				return nil
			}
			name, ok := args[0].(string)
			if !ok || strings.HasPrefix(name, "-") {
				return nil
			}
			if choices, ok := e.kw["choices"]; ok {
				if found := textsOf(m.eval(choices, s)); len(found) > 0 {
					r.choices, r.chosen = found, true
				}
			}
		}
	case *subparsers:
		if method != "add_parser" || len(args) == 0 {
			return nil
		}
		name, ok := args[0].(string)
		if !ok {
			return nil
		}
		child := newParser()
		if _, held := r.parser.child[name]; !held {
			r.parser.children = append(r.parser.children, name)
		}
		r.parser.child[name] = child
		return child
	case texts:
		switch method {
		case "keys", "items", "values", "copy":
			return r
		}
	}
	return nil
}

// work_tickets.py's registry: `COMMANDS = Command(...)`, `<GROUP> = command_group(<name>, ...)`
// and each `@command(<name>, ..., parent=<GROUP>)`, whose leaf's first positional `arg` with
// `choices` gives its own tree, as build_parser builds each command's parser.

func (m *module) registry() bool {
	_, group := m.functions["command_group"]
	_, command := m.functions["command"]
	toks, ok := m.constants["COMMANDS"]
	return group && command && ok && len(toks) > 0 && toks[0].text == "Command"
}

func (m *module) registryTree() Tree {
	type entry struct {
		parent string
		name   string
		node   *parserNode
	}
	groups := map[string]*parserNode{"COMMANDS": newParser()}
	groups["COMMANDS"].sub = true
	add := func(parent *parserNode, name string, node *parserNode) {
		if _, held := parent.child[name]; !held {
			parent.children = append(parent.children, name)
		}
		parent.child[name], parent.sub = node, true
	}
	s := &scope{vars: map[string]any{}}
	for _, st := range m.stmts {
		if st.indent != 0 {
			continue
		}
		toks := st.tokens
		if at := assignment(toks); at == 1 && toks[0].kind == 'n' {
			e := parseExpr(toks[2:])
			if e.kind == "call" && e.of.kind == "name" && e.of.text == "command_group" && len(e.items) > 0 {
				if name, ok := m.eval(e.items[0], s).(string); ok {
					group := newParser()
					add(groups["COMMANDS"], name, group)
					groups[toks[0].text] = group
				}
			}
			continue
		}
		if !isOp(toks[0], "@") {
			continue
		}
		e := parseExpr(toks[1:])
		if e.kind != "call" || e.of.kind != "name" || e.of.text != "command" || len(e.items) == 0 {
			continue
		}
		name, ok := m.eval(e.items[0], s).(string)
		if !ok {
			continue
		}
		parent := "COMMANDS"
		if p, ok := e.kw["parent"]; ok && p.kind == "name" {
			parent = p.text
		}
		group, ok := groups[parent]
		if !ok {
			continue
		}
		leaf := newParser()
		for _, argument := range e.items[1:] {
			if argument.kind != "call" || argument.of.kind != "name" || argument.of.text != "arg" || len(argument.items) == 0 {
				continue
			}
			flag, ok := m.eval(argument.items[0], s).(string)
			if !ok || strings.HasPrefix(flag, "-") {
				continue
			}
			if choices, ok := argument.kw["choices"]; ok {
				if found := textsOf(m.eval(choices, s)); len(found) > 0 {
					leaf.choices, leaf.chosen = found, true
					break
				}
			}
		}
		add(group, name, leaf)
	}
	return groups["COMMANDS"].tree()
}
