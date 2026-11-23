package template

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// The names and sets the format reads, each as scripts/templates.py declares it.
const (
	TemplatesFolder   = "templates"
	TermsFile         = "terms.toml"
	templateSuffix    = ".md"
	FleetMarker       = "<!-- se:fleet -->"
	SERepository      = "se"
	ProjectRepository = "project"
	FileAction        = "file.write"
	MessageAction     = "message.send"
	interfaceKind     = "interface"
	NotInInput        = "Not in input"
	Refuse            = "refuse"
	Warn              = "warn"
	Off               = "off"
	nodeRule          = "node"
	versionRule       = "version"
	quoteRule         = "quote"
)

var (
	// Actions are the writes a template shapes.
	Actions        = []string{"issue.create", "issue.edit", "pr.create", "pr.edit", "pr.merge", "comment.create", "comment.edit", "deck.build", FileAction, MessageAction}
	readers        = []string{"owner", "fleet"}
	fieldKinds     = []string{"line", "text", "choice", "list", "object", "issue", "checklist", "code", "node", "register"}
	templateKinds  = []string{"document", "block", "entry", "interface"}
	partKinds      = []string{"block", "entry"}
	refuseRules    = []string{"required", "choice", "not-picked", "duplicate", "dangling"}
	warnRules      = []string{"words", "first-sentence", "actor", "one-sentence", "bare-number", "board", "terms", "unnamed-entry", "title-shape"}
	fieldKeys      = set("name", "kind", "heading", "required", "none_ok", "says", "exact_heading", "verbatim", "source", "label", "choices", "numbered", "continue_numbers", "markers", "lang", "max_words", "first_sentence_chars", "actor", "one_sentence", "not_picked", "shape", "quote", "node", "entries", "fence")
	templateKeys   = set("name", "version", "kind", "tags", "reader", "says", "applies", "extends", "remove", "order", "keep_unknown", "rules", "actors", "example", "scope", "fields", "checker", "adapter", "message")
	appliesKeys    = set("actions", "order", "marker", "marker_pattern", "title", "labels", "base", "fallback", "paths")
	adapterKeys    = set("extract", "extract_with", "json_after", "sections", "drop", "missing", "text_as", "title_as", "with", "none", "when", "result", "refusal", "title_rule", "lines")
	results        = []string{"problems", "raises", "truth"}
	reference      = regexp.MustCompile(`^[a-z_][a-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*$`)
	nodePin        = regexp.MustCompile(`^([\w-]+)@((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))$`)
	semver         = regexp.MustCompile(`^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$`)
	instruction    = regexp.MustCompile(`^[ \t\r\n]*<!--[ \t\r\n]*([a-z_][a-z0-9_]*):[ \t\r\n]*((?s:.*?))[ \t\r\n]*-->[ \t\r\n]*$`)
	fenceWord      = regexp.MustCompile(`^[\w-]+$`)
	placeholderRef = regexp.MustCompile(`\{([a-z_][a-z0-9_]*)\}`)
)

func set(items ...string) map[string]bool {
	m := map[string]bool{}
	for _, item := range items {
		m[item] = true
	}
	return m
}

func in(item string, items []string) bool {
	for _, x := range items {
		if x == item {
			return true
		}
	}
	return false
}

// Error is a template that does not load, or a usage the engine refuses: its message names the
// file or the argument and the remedy.
type Error struct{ Msg string }

func (e *Error) Error() string { return e.Msg }

func fail(format string, args ...any) error { return &Error{fmt.Sprintf(format, args...)} }

// Field is one field of a template; scripts/templates.py's docstring ("Fields") owns each key.
type Field struct {
	Name               string
	Kind               string
	Heading            string
	Required           bool
	NoneOK             bool
	Says               string
	ExactHeading       bool
	Verbatim           bool
	Source             string
	Label              string
	Choices            []string
	Numbered           bool
	ContinueNumbers    bool
	Markers            bool
	Lang               string
	MaxWords           int
	FirstSentenceChars int
	Actor              bool
	OneSentence        bool
	NotPicked          bool
	Shape              string
	Quote              bool
	Node               string
	Pin                string
	Fence              string
	rule               any // a *regexp.Regexp or a ShapeFunc that shape names
	nested             *Template
}

// InBody reports whether the field has a section of its own (not the title, a label or a fence).
func (f *Field) InBody() bool { return f.Source == "" && f.Label == "" && f.Fence == "" }

// Term is an inside term and the plain words a reader outside knows.
type Term struct{ Term, Plain string }

// Template is a loaded template, its extends and its nodes resolved.
type Template struct {
	Name          string
	Reader        string
	Says          string
	Actions       []string
	Fields        []*Field
	Rules         Object
	Order         int
	Marker        string
	TitlePattern  string
	KeepUnknown   bool
	Actors        []string
	Example       Object
	Scope         Object
	Terms         []Term
	Path          string
	MarkerPattern string
	Labels        []string
	Base          string
	Fallback      bool
	Checker       string
	Adapter       Object
	Paths         []string
	Repository    string
	Version       string
	Kind          string
	Tags          []string
	Digest        string
	Message       string
}

// MarkerLine is the template's marker, `<!-- se:template <repository>/<name> <version> <digest> -->`.
func (t *Template) MarkerLine() string {
	return fmt.Sprintf("<!-- se:template %s/%s %s %s -->", t.Repository, t.Name, t.Version, t.Digest)
}

// frontLines are what a claimed file's front matter records: its template, version and overlay.
func (t *Template) frontLines() [][2]string {
	return [][2]string{{"template", t.Repository + "/" + t.Name}, {"version", t.Version}, {"overlay", t.Digest}}
}

// IsFile reports whether the template shapes files (file.write), claimed by its paths.
func (t *Template) IsFile() bool { return in(FileAction, t.Actions) }

// Claims reports whether one of the template's paths matches path, relative to the project root.
func (t *Template) Claims(path string) bool {
	for _, glob := range t.Paths {
		if globPattern(glob).MatchString(path) {
			return true
		}
	}
	return false
}

// IsAdapter reports whether the template is an adapter: no fields, a check SE already has.
func (t *Template) IsAdapter() bool { return len(t.Fields) == 0 }

// Field answers the field named name, nil where there is none.
func (t *Template) Field(name string) *Field {
	for _, f := range t.Fields {
		if f.Name == name {
			return f
		}
	}
	return nil
}

// Severity is how the template marks rule: refuse, warn or off.
func (t *Template) Severity(rule string) string {
	if v, ok := t.Rules.Get(rule); ok {
		return str(v)
	}
	return Off
}

// Level is the heading level of the template's sections: 2, or the scope's.
func (t *Template) Level() int {
	if len(t.Scope) > 0 {
		if v, ok := t.Scope.Get("level"); ok {
			if n, ok := v.(int); ok {
				return n
			}
		}
	}
	return 2
}

// Catalog is every template of a load, by name.
type Catalog map[string]*Template

// Layer is one place templates resolve from: its repository's name in the marker, its files
// (`templates/<file>` to its text) and how a finding names a file of it.
type Layer struct {
	Repository string
	Files      map[string]string
	Where      func(name string) string
}

// Load reads the templates of the layers, first first: a name, and the term list, are the first
// layer's that holds it (scripts/templates.py `_loaded`).
func Load(layers ...Layer) (Catalog, error) {
	raw := map[string]Object{}
	texts := map[string]string{}
	repositories := map[string]string{}
	var terms []Term
	termsRead := false
	for _, layer := range layers {
		for _, name := range sortedKeys(layer.Files) {
			text := layer.Files[name]
			where := layer.Where(name)
			if name == TermsFile {
				found, err := readTerms(text, where)
				if err != nil {
					return nil, err
				}
				if !termsRead {
					terms, termsRead = found, true
				}
				continue
			}
			if !strings.HasSuffix(name, templateSuffix) {
				continue
			}
			data, err := noteData(text, where)
			if err != nil {
				return nil, err
			}
			own := strings.TrimSuffix(name, templateSuffix)
			named, _ := data.Get("name")
			if s, ok := named.(string); !ok || s != own {
				return nil, fail("%s: name: %s must be the file's name, %s", where, repr(named), repr(own))
			}
			if _, taken := raw[own]; taken {
				continue
			}
			data.Set("path", where)
			raw[own], texts[own], repositories[own] = data, text, layer.Repository
		}
	}
	built := map[string]*Template{}
	for _, name := range sortedKeys(raw) {
		t, err := build(name, raw, terms, nil)
		if err != nil {
			return nil, err
		}
		built[name] = t
	}
	digests := map[string]string{}
	for name, t := range built {
		digests[name] = digestOf(name, raw, texts)
		t.Repository, t.Digest = repositories[name], digests[name]
	}
	return nest(built, digests)
}

func digestOf(name string, raw map[string]Object, texts map[string]string) string {
	chain := sha256.New()
	for {
		text, ok := texts[name]
		if !ok {
			break
		}
		chain.Write([]byte(text))
		chain.Write([]byte{0})
		next, _ := raw[name].Get("extends")
		s, _ := next.(string)
		name = s
	}
	return "sha256:" + hex.EncodeToString(chain.Sum(nil))
}

// readTerms reads templates/terms.toml: its [[terms]] tables of term and plain.
func readTerms(text, where string) ([]Term, error) {
	var terms []Term
	var current *Term
	for i, line := range splitLines(text, false) {
		line = strip(line)
		switch {
		case line == "" || strings.HasPrefix(line, "#"):
		case line == "[[terms]]":
			terms = append(terms, Term{})
			current = &terms[len(terms)-1]
		default:
			key, value, ok := strings.Cut(line, "=")
			if !ok {
				return nil, fail("%s: not TOML (line %d: %s); fix the file", where, i+1, line)
			}
			v, err := decodeJSON(strip(value))
			s, isString := v.(string)
			if err != nil || !isString {
				return nil, fail("%s: not TOML (line %d: %s); fix the file", where, i+1, line)
			}
			if current == nil {
				continue
			}
			switch strip(key) {
			case "term":
				current.Term = s
			case "plain":
				current.Plain = s
			}
		}
	}
	return terms, nil
}

// noteData reads a template note as the data build reads: its front matter, each field of its
// skeleton given its heading and says from its section.
func noteData(text, where string) (Object, error) {
	text = strings.ReplaceAll(text, "\r\n", "\n")
	if !strings.HasPrefix(text, "---\n") {
		return nil, fail("%s: a template opens with its front matter between `---` lines", where)
	}
	end := strings.Index(text[3:], "\n---\n")
	if end >= 0 {
		end += 3
	}
	if end < 0 && strings.HasSuffix(text, "\n---") {
		end = len(text) - 4
	}
	if end < 0 {
		return nil, fail("%s: the front matter has no closing `---` line", where)
	}
	data, err := FrontData(text[4:end+1], where, 2)
	if err != nil {
		return nil, err
	}
	body := ""
	if end+5 <= len(text) {
		body = text[end+5:]
	}
	first := strings.Count(text[:min(end+5, len(text))], "\n") + 1
	fieldsValue, has := data.Get("fields")
	if !has {
		fieldsValue = []any{}
	}
	list, ok := fieldsValue.([]any)
	if ok {
		for _, entry := range list {
			if _, isObject := entry.(Object); !isObject {
				ok = false
			}
		}
	}
	if !ok {
		return nil, fail("%s: fields is a list of mappings, one per field", where)
	}
	level := 2
	if scope, ok := data.Value("scope").(Object); ok && len(scope) > 0 {
		if v, ok := scope.Value("level").(int); ok {
			level = v
		} else if v, has := scope.Get("level"); has {
			return nil, fail("%s: scope level is %s; write a whole number", where, repr(v))
		}
	}
	if data.Value("kind") == interfaceKind {
		return interfaceData(data, list, body, where, first)
	}
	sections, err := skeleton(body, where, first, level)
	if err != nil {
		return nil, err
	}
	var inBody []Object
	var at []int
	for i, e := range list {
		entry := e.(Object)
		if !truthy(entry.Value("source")) && !truthy(entry.Value("label")) && !truthy(entry.Value("fence")) {
			inBody = append(inBody, entry)
			at = append(at, i)
		}
	}
	for _, entry := range inBody {
		for _, key := range []string{"heading", "says"} {
			if entry.Has(key) {
				name := "?"
				if v, ok := entry.Get("name"); ok {
					name = str(v)
				}
				return nil, fail("%s: field %s has its section in the skeleton, which owns its %s; take %s out of the front matter", where, name, key, key)
			}
		}
	}
	named := make([]string, len(inBody))
	for i, entry := range inBody {
		named[i] = str(entry.Value("name"))
	}
	listed := make([]string, len(sections))
	for i, s := range sections {
		listed[i] = s[0]
	}
	if strings.Join(listed, "\x00") != strings.Join(named, "\x00") || len(listed) != len(named) {
		return nil, fail("%s: the skeleton's sections are %s; they are one per field with a section, in the front matter's order: %s", where, orNone(listed), orNone(named))
	}
	for i, entry := range inBody {
		entry.Set("heading", sections[i][1])
		entry.Set("says", sections[i][2])
		list[at[i]] = entry
	}
	return data, nil
}

func orNone(items []string) string {
	if len(items) == 0 {
		return "none"
	}
	return joinStrings(items)
}

func interfaceData(data Object, list []any, body, where string, first int) (Object, error) {
	for i, line := range splitLines(body, false) {
		if strip(line) != "" {
			return nil, fail("%s:%d: an interface's body is empty; its fields, in the front matter, are the whole template", where, first+i)
		}
	}
	message := data.Value("message")
	for _, e := range list {
		entry := e.(Object)
		name := "?"
		if v, ok := entry.Get("name"); ok {
			name = str(v)
		}
		says := ""
		if v, ok := entry.Get("says"); ok {
			says = str(v)
		}
		if strip(says) == "" {
			return nil, fail("%s: field %s of an interface says what belongs there in the front matter, `says`", where, name)
		}
		if truthy(message) && entry.Has("heading") {
			return nil, fail("%s: field %s is a part of the message line, which has no headings; take heading out", where, name)
		}
	}
	return data, nil
}

func skeleton(body, where string, first, level int) ([][3]string, error) {
	type section struct {
		heading string
		number  int
		lines   []string
	}
	var sections []*section
	var current *section
	hashes := strings.Repeat("#", level)
	for i, line := range splitLines(body, false) {
		number := first + i
		match := heading.FindStringSubmatch(line)
		if match != nil && len(match[1]) == level {
			current = &section{heading: match[2], number: number}
			sections = append(sections, current)
			continue
		}
		if match != nil {
			return nil, fail("%s:%d: %s is no section of the skeleton; its sections are `%s <heading>` lines", where, number, line, hashes)
		}
		if current == nil {
			if strip(line) != "" {
				return nil, fail("%s:%d: text before the skeleton's first section; a comment on the template goes in the front matter, after `#`", where, number)
			}
			continue
		}
		current.lines = append(current.lines, line)
	}
	var made [][3]string
	for _, s := range sections {
		found := instruction.FindStringSubmatch(strings.Join(s.lines, "\n"))
		if found == nil {
			return nil, fail("%s:%d: section %s holds one comment alone, `<!-- <field>: <instruction> -->`", where, s.number, s.heading)
		}
		made = append(made, [3]string{found[1], s.heading, joinWords(found[2])})
	}
	return made, nil
}

func objectOf(v any) (Object, bool) {
	o, ok := v.(Object)
	return o, ok
}

func stringsOf(v any) []string {
	switch x := v.(type) {
	case []any:
		out := make([]string, len(x))
		for i, item := range x {
			out[i] = str(item)
		}
		return out
	case []string:
		return x
	case string:
		out := make([]string, 0, len(x))
		for _, r := range x {
			out = append(out, string(r))
		}
		return out
	case Object:
		return x.Keys()
	}
	return nil
}

func build(name string, raw map[string]Object, terms []Term, seen []string) (*Template, error) {
	data := raw[name]
	where := str(data.Value("path"))
	var unknown []string
	for _, key := range data.Keys() {
		if !templateKeys[key] && key != "path" {
			unknown = append(unknown, key)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return nil, fail("%s: unknown keys %s; the template file format is scripts/templates.py's docstring", where, joinStrings(unknown))
	}
	var parent *Template
	if data.Has("extends") {
		base := str(data.Value("extends"))
		if in(base, seen) || base == name {
			return nil, fail("%s: extends %s in a cycle (%s)", where, repr(data.Value("extends")), strings.Join(append(append([]string{}, seen...), name), " -> "))
		}
		if _, ok := raw[base]; !ok {
			return nil, fail("%s: extends %s, which is no template in %s/", where, repr(data.Value("extends")), TemplatesFolder)
		}
		var err error
		parent, err = build(base, raw, terms, append(append([]string{}, seen...), name))
		if err != nil {
			return nil, err
		}
	}
	appliesValue, hasApplies := data.Get("applies")
	applies, appliesIsObject := objectOf(appliesValue)
	if appliesIsObject {
		var extra []string
		for _, key := range applies.Keys() {
			if !appliesKeys[key] {
				extra = append(extra, key)
			}
		}
		if len(extra) > 0 {
			sort.Strings(extra)
			return nil, fail("%s: applies has unknown keys %s; the keys are %s", where, joinStrings(extra), joinStrings(sortedKeys(appliesKeys)))
		}
	}
	kindValue := data.Value("kind")
	isPart := false
	if s, ok := kindValue.(string); ok && in(s, partKinds) {
		isPart = true
	}
	switch {
	case (!hasApplies || appliesValue == nil) && parent == nil && isPart:
		applies = Object{{"actions", []any{}}}
	case !appliesIsObject || !truthy(applies.Value("actions")):
		if parent == nil {
			msg := fmt.Sprintf("%s: applies.actions is required; name the actions the template shapes (%s)", where, joinStrings(Actions))
			if isPart {
				msg += ", or leave applies out of a block or an entry that only a node checks"
			}
			return nil, &Error{msg}
		}
		merged := Object{{"actions", toAny(parent.Actions)}}
		if appliesIsObject {
			for _, pair := range applies {
				merged.Set(pair.Key, pair.Value)
			}
		}
		applies = merged
	}
	actions := stringsOf(applies.Value("actions"))
	for _, action := range actions {
		if !in(action, Actions) {
			return nil, fail("%s: action %s is none of %s", where, repr(action), joinStrings(Actions))
		}
	}
	version, kind, tags := data.Value("version"), kindValue, data.Value("tags")
	if s, ok := version.(string); !ok || !semver.MatchString(s) {
		return nil, fail("%s: version is %s; write the template's semantic version, such as 1.2.0", where, repr(version))
	}
	if s, ok := kind.(string); !ok || !in(s, templateKinds) {
		return nil, fail("%s: kind is %s; one of %s", where, repr(kind), joinStrings(templateKinds))
	}
	tagList, ok := tags.([]any)
	if ok {
		for _, tag := range tagList {
			if s, isString := tag.(string); !isString || strip(s) == "" {
				ok = false
			}
		}
	}
	if !ok {
		return nil, fail("%s: tags is a list of words, the template's link to guidance, such as [\"issue\"]", where)
	}
	reader := any("")
	if parent != nil {
		reader = parent.Reader
	}
	if v, has := data.Get("reader"); has {
		reader = v
	}
	if s, ok := reader.(string); !ok || !in(s, readers) {
		return nil, fail("%s: reader %s is none of %s", where, repr(reader), joinStrings(readers))
	}
	var fields []*Field
	removed := map[string]bool{}
	for _, item := range stringsOf(data.Value("remove")) {
		removed[item] = true
	}
	if parent != nil {
		for _, f := range parent.Fields {
			if !removed[f.Name] {
				fields = append(fields, f)
			}
		}
	}
	message := data.Value("message")
	if message == nil {
		message = ""
	}
	entries, _ := data.Value("fields").([]any)
	for _, e := range entries {
		made, err := makeField(e.(Object), where, !truthy(message))
		if err != nil {
			return nil, err
		}
		replaced := false
		for i, f := range fields {
			if f.Name == made.Name {
				fields[i], replaced = made, true
				break
			}
		}
		if !replaced {
			fields = append(fields, made)
		}
	}
	if data.Has("order") {
		order := stringsOf(data.Value("order"))
		names := make([]string, len(fields))
		for i, f := range fields {
			names[i] = f.Name
		}
		a, b := append([]string{}, order...), append([]string{}, names...)
		sort.Strings(a)
		sort.Strings(b)
		if strings.Join(a, "\x00") != strings.Join(b, "\x00") || len(a) != len(b) {
			return nil, fail("%s: order must list every field once: %s", where, joinStrings(names))
		}
		position := map[string]int{}
		for i, n := range order {
			if _, ok := position[n]; !ok {
				position[n] = i
			}
		}
		sort.SliceStable(fields, func(i, j int) bool { return position[fields[i].Name] < position[fields[j].Name] })
	}
	rules := Object{}
	if parent != nil {
		rules = parent.Rules.Copy()
	}
	if own, ok := data.Value("rules").(Object); ok {
		for _, pair := range own {
			rules.Set(pair.Key, pair.Value)
		}
	}
	for _, pair := range rules {
		severity := pair.Value
		if !in(pair.Key, refuseRules) && !in(pair.Key, warnRules) {
			return nil, fail("%s: rule %s is unknown; the rules are %s", where, repr(pair.Key), joinStrings(append(append([]string{}, refuseRules...), warnRules...)))
		}
		if s, ok := severity.(string); !ok || (s != Refuse && s != Warn && s != Off) {
			return nil, fail("%s: rule %s is %s; mark it refuse, warn or off", where, pair.Key, repr(severity))
		}
		if in(pair.Key, warnRules) && severity == Refuse {
			return nil, fail("%s: rule %s only warns, never refuses; mark it warn", where, pair.Key)
		}
	}
	example, _ := data.Value("example").(Object)
	adapter, err := adapterOf(data, where, fields, parent)
	if err != nil {
		return nil, err
	}
	if err := checkMessage(message, kind, fields, parent, where); err != nil {
		return nil, err
	}
	baseBranch := ""
	if parent != nil {
		baseBranch = parent.Base
	}
	if v, ok := applies.Get("base"); ok {
		baseBranch = str(v)
	}
	if baseBranch != "" && baseBranch != "integration" {
		return nil, fail("%s: applies.base is %s; the one base is \"integration\", the integration branch", where, repr(baseBranch))
	}
	var pathsValue any = []any{}
	if parent != nil {
		pathsValue = toAny(parent.Paths)
	}
	if v, ok := applies.Get("paths"); ok {
		pathsValue = v
	}
	pathList, ok := pathsValue.([]any)
	if ok {
		for _, glob := range pathList {
			if s, isString := glob.(string); !isString || strip(s) == "" {
				ok = false
			}
		}
	}
	if !ok {
		return nil, fail("%s: applies.paths is a list of globs relative to the project root, such as \"book/*/steps/*.md\"", where)
	}
	if len(pathList) > 0 && !(len(actions) > 0 && allEqual(actions, FileAction)) {
		return nil, fail("%s: applies.paths claims files and goes only with actions: [\"%s\"]; take out paths, or the other actions", where, FileAction)
	}
	if in(FileAction, actions) && len(pathList) == 0 {
		return nil, fail("%s: action %s needs applies.paths, the globs of the files the template claims", where, FileAction)
	}
	markerPattern := ""
	if v, ok := applies.Get("marker_pattern"); ok {
		markerPattern = str(v)
	}
	if _, err := regexp.Compile(markerPattern); err != nil {
		return nil, fail("%s: applies.marker_pattern is no regular expression (%s)", where, err)
	}
	t := &Template{
		Name: name, Version: version.(string), Kind: kind.(string), Reader: reader.(string),
		Actions: actions, Fields: fields, Rules: rules, Terms: terms, Path: where,
		MarkerPattern: markerPattern, Base: baseBranch, Checker: "", Adapter: adapter,
		Message: str(message), Order: 100, KeepUnknown: true,
	}
	for _, tag := range tagList {
		t.Tags = append(t.Tags, tag.(string))
	}
	if parent != nil {
		t.Says, t.Order, t.KeepUnknown, t.Actors, t.Labels = parent.Says, parent.Order, parent.KeepUnknown, parent.Actors, parent.Labels
	}
	if v, ok := data.Get("says"); ok {
		t.Says = str(v)
	}
	if v, ok := applies.Get("order"); ok {
		n, isInt := v.(int)
		if !isInt {
			return nil, fail("%s: applies.order is %s; write a whole number", where, repr(v))
		}
		t.Order = n
	}
	if v, ok := applies.Get("marker"); ok {
		t.Marker = str(v)
	}
	if v, ok := applies.Get("title"); ok {
		t.TitlePattern = str(v)
	}
	if v, ok := data.Get("keep_unknown"); ok {
		t.KeepUnknown = truthy(v)
	}
	if v, ok := data.Get("actors"); ok {
		t.Actors = stringsOf(v)
	}
	if len(example) > 0 {
		t.Example = example
	}
	if v, ok := data.Value("scope").(Object); ok {
		t.Scope = v
	}
	if v, ok := applies.Get("labels"); ok {
		t.Labels = stringsOf(v)
	}
	t.Fallback = truthy(applies.Value("fallback"))
	if v, ok := data.Get("checker"); ok {
		t.Checker = str(v)
	}
	for _, glob := range pathList {
		t.Paths = append(t.Paths, strings.Trim(strip(glob.(string)), "/"))
	}
	return t, nil
}

func allEqual(items []string, want string) bool {
	for _, item := range items {
		if item != want {
			return false
		}
	}
	return true
}

func toAny(items []string) []any {
	out := make([]any, len(items))
	for i, item := range items {
		out[i] = item
	}
	return out
}

func checkMessage(message, kind any, fields []*Field, parent *Template, where string) error {
	if !truthy(message) {
		return nil
	}
	s, ok := message.(string)
	if !ok || strings.Contains(s, "\n") {
		return fail("%s: message is one line, its fields as {<field>}", where)
	}
	if kind != interfaceKind || parent != nil || len(fields) == 0 {
		return fail("%s: message is an interface's own line: kind interface, with fields, extending no template", where)
	}
	named := placeholders(s)
	names := make([]string, len(fields))
	for i, f := range fields {
		names[i] = f.Name
	}
	a, b := append([]string{}, named...), append([]string{}, names...)
	sort.Strings(a)
	sort.Strings(b)
	if strings.Join(a, "\x00") != strings.Join(b, "\x00") || len(a) != len(b) {
		n := "no field"
		if len(named) > 0 {
			n = joinStrings(named)
		}
		return fail("%s: message names %s; it names each field once: %s", where, n, joinStrings(names))
	}
	for _, f := range fields {
		if (f.Kind != "line" && f.Kind != "choice") || f.Source != "" || f.Label != "" || f.Node != "" {
			return fail("%s: field %s of a message is a line or a choice, one line of the message", where, f.Name)
		}
	}
	return nil
}

func placeholders(message string) []string {
	var names []string
	for _, m := range placeholderRef.FindAllStringSubmatch(message, -1) {
		names = append(names, m[1])
	}
	return names
}

// globPattern is a path glob as a pattern of a whole `/`-separated path: `*` and `?` within one
// folder, `**` across folders.
func globPattern(glob string) *regexp.Regexp {
	var out strings.Builder
	for i := 0; i < len(glob); {
		switch {
		case strings.HasPrefix(glob[i:], "**/"):
			out.WriteString("(?:[^/]*/)*")
			i += 3
		case strings.HasPrefix(glob[i:], "**"):
			out.WriteString(".*")
			i += 2
		case glob[i] == '*':
			out.WriteString("[^/]*")
			i++
		case glob[i] == '?':
			out.WriteString("[^/]")
			i++
		default:
			out.WriteString(regexp.QuoteMeta(glob[i : i+1]))
			i++
		}
	}
	return regexp.MustCompile("^(?s:" + out.String() + ")$")
}

func adapterOf(data Object, where string, fields []*Field, parent *Template) (Object, error) {
	value, has := data.Get("adapter")
	if !has {
		value = Object{}
	}
	if len(fields) > 0 {
		if data.Has("checker") || truthy(value) {
			return nil, fail("%s: a template with fields takes no checker or adapter; an adapter is a template without fields", where)
		}
		return Object{}, nil
	}
	if parent != nil {
		return nil, fail("%s: an adapter extends no template", where)
	}
	adapter, ok := value.(Object)
	var extra []string
	if ok {
		for _, key := range adapter.Keys() {
			if !adapterKeys[key] {
				extra = append(extra, key)
			}
		}
	} else {
		extra = []string{"?"}
	}
	if len(extra) > 0 {
		sort.Strings(extra)
		return nil, fail("%s: adapter has unknown keys %s; the keys are %s (scripts/templates.py's docstring)", where, joinStrings(extra), joinStrings(sortedKeys(adapterKeys)))
	}
	for _, v := range []any{data.Value("checker"), adapter.Value("extract"), adapter.Value("when"), adapter.Value("title_rule")} {
		if truthy(v) && !reference.MatchString(str(v)) {
			return nil, fail("%s: %s is no \"<module>:<name>\" of a script beside scripts/templates.py", where, repr(v))
		}
	}
	result := any("problems")
	if v, ok := adapter.Get("result"); ok {
		result = v
	}
	if s, ok := result.(string); !ok || !in(s, results) {
		return nil, fail("%s: adapter.result is %s; one of %s", where, repr(adapter.Value("result")), joinStrings(results))
	}
	missing := any(Refuse)
	if v, ok := adapter.Get("missing"); ok {
		missing = v
	}
	if missing != Refuse && missing != Warn && missing != "pass" {
		return nil, fail("%s: adapter.missing is %s; one of refuse, warn, pass", where, repr(adapter.Value("missing")))
	}
	if adapter.Value("result") == "truth" && !truthy(adapter.Value("refusal")) {
		return nil, fail("%s: adapter.result \"truth\" needs its refusal, the fix a false answer gives", where)
	}
	lines, _ := adapter.Value("lines").([]any)
	for _, l := range lines {
		line, ok := l.(Object)
		valid := ok
		if ok {
			for _, key := range line.Keys() {
				if key != "pattern" && key != "first" && key != "says" {
					valid = false
				}
			}
		}
		if !valid || !truthy(line.Value("pattern")) || !truthy(line.Value("says")) {
			return nil, fail("%s: each item of adapter.lines has a pattern and says, and may set first", where)
		}
		if _, err := regexp.Compile(str(line.Value("pattern"))); err != nil {
			return nil, fail("%s: adapter.lines pattern %s is no regular expression (%s)", where, repr(line.Value("pattern")), err)
		}
	}
	return adapter, nil
}

func makeField(entry Object, where string, sectioned bool) (*Field, error) {
	name := "?"
	if v, ok := entry.Get("name"); ok {
		name = str(v)
	}
	var unknown []string
	for _, key := range entry.Keys() {
		if !fieldKeys[key] {
			unknown = append(unknown, key)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return nil, fail("%s: field %s has unknown keys %s", where, name, joinStrings(unknown))
	}
	entry, err := nodeEntry(entry.Copy(), where, name)
	if err != nil {
		return nil, err
	}
	kind, _ := entry.Value("kind").(string)
	if !in(kind, fieldKinds) {
		return nil, fail("%s: field %s has kind %s; one of %s", where, name, repr(entry.Value("kind")), joinStrings(fieldKinds))
	}
	var choices []string
	seen := map[string]bool{}
	add := func(choice string) {
		if !seen[choice] {
			seen[choice] = true
			choices = append(choices, choice)
		}
	}
	for _, c := range stringsOf(entry.Value("choices")) {
		if reference.MatchString(c) {
			named, ok := References[c]
			if !ok {
				return nil, fail("%s: field %s choices: %s does not resolve (the Go engine holds no %s); name a script beside scripts/templates.py and what it defines", where, name, c, c)
			}
			list, isList := named.([]string)
			if !isList {
				return nil, fail("%s: field %s choices: %s is no list or mapping; name one whose items or keys are the choices", where, name, c)
			}
			for _, item := range list {
				add(item)
			}
		} else {
			add(c)
		}
	}
	f := &Field{Name: str(entry.Value("name")), Kind: kind, Choices: choices, Lang: "sh"}
	f.Heading = optionalString(entry, "heading")
	f.Says = optionalString(entry, "says")
	f.Source = optionalString(entry, "source")
	f.Label = optionalString(entry, "label")
	f.Shape = optionalString(entry, "shape")
	f.Node = optionalString(entry, "node")
	f.Pin = optionalString(entry, "pin")
	f.Fence = optionalString(entry, "fence")
	if entry.Has("lang") {
		f.Lang = str(entry.Value("lang"))
	}
	f.Required = truthy(entry.Value("required"))
	f.NoneOK = truthy(entry.Value("none_ok"))
	f.ExactHeading = truthy(entry.Value("exact_heading"))
	f.Verbatim = truthy(entry.Value("verbatim"))
	f.Numbered = truthy(entry.Value("numbered"))
	f.ContinueNumbers = truthy(entry.Value("continue_numbers"))
	f.Markers = truthy(entry.Value("markers"))
	f.Actor = truthy(entry.Value("actor"))
	f.OneSentence = truthy(entry.Value("one_sentence"))
	f.NotPicked = truthy(entry.Value("not_picked"))
	f.Quote = truthy(entry.Value("quote"))
	if v, ok := entry.Get("max_words"); ok {
		n, isInt := v.(int)
		if !isInt {
			return nil, fail("%s: field %s max_words is %s; write a whole number", where, name, repr(v))
		}
		f.MaxWords = n
	}
	if reference.MatchString(f.Shape) {
		rule, ok := References[f.Shape]
		if !ok {
			return nil, fail("%s: field %s shape: %s does not resolve (the Go engine holds no %s); name a script beside scripts/templates.py and what it defines", where, name, f.Shape, f.Shape)
		}
		switch rule.(type) {
		case *regexp.Regexp, ShapeFunc:
			f.rule = rule
		default:
			return nil, fail("%s: field %s shape: %s is no pattern or function; name a compiled pattern or a function that gives the warning", where, name, f.Shape)
		}
	}
	charsValue := any(0)
	if v, ok := entry.Get("first_sentence_chars"); ok {
		charsValue = v
	}
	if n, ok := charsValue.(int); !ok || n < 0 {
		return nil, fail("%s: field %s first_sentence_chars is %s; write a whole number, 0 for none", where, name, repr(charsValue))
	} else {
		f.FirstSentenceChars = n
	}
	if sectioned && f.InBody() && f.Heading == "" {
		return nil, fail("%s: field %s needs a heading (or source = \"title\", or a label)", where, name)
	}
	if f.Kind == "choice" && len(f.Choices) == 0 {
		return nil, fail("%s: field %s is a choice without choices", where, name)
	}
	return f, nil
}

func optionalString(entry Object, key string) string {
	if v, ok := entry.Get(key); ok {
		return str(v)
	}
	return ""
}

func nodeEntry(entry Object, where, name string) (Object, error) {
	var given []string
	for _, key := range []string{"node", "entries"} {
		if entry.Has(key) {
			given = append(given, key)
		}
	}
	if len(given) > 1 {
		return nil, fail("%s: field %s is a node or a register, not both; keep `node:` or `entries:`", where, name)
	}
	if len(given) == 0 {
		if kind, ok := entry.Value("kind").(string); ok && (kind == "node" || kind == "register") {
			return nil, fail("%s: field %s has kind %s without its template; write `node: <template>@<version>` or `entries: <template>@<version>`", where, name, kind)
		}
		if entry.Has("fence") {
			return nil, fail("%s: field %s has a fence but is no node; write `node: <template>@<version>` beside it", where, name)
		}
		return entry, nil
	}
	key := given[0]
	kind := "register"
	if key == "node" {
		kind = "node"
	}
	pinned := str(entry.Value(key))
	entry.Delete(key)
	pin := nodePin.FindStringSubmatch(pinned)
	if pin == nil {
		return nil, fail("%s: field %s %s: write the template and the version it pins, `<template>@<version>`, such as raid-entry@1.0.0", where, name, key)
	}
	if v, ok := entry.Get("kind"); ok && v != kind {
		return nil, fail("%s: field %s is a %s (%s:) and takes no kind %s; leave kind out", where, name, kind, key, str(v))
	}
	fence := entry.Value("fence")
	if truthy(fence) && (kind != "node" || !fenceWord.MatchString(str(fence))) {
		return nil, fail("%s: field %s fence: a node's fence is its info word, such as pugh, and goes with `node:` alone", where, name)
	}
	var extra []string
	for _, k := range []string{"choices", "numbered", "continue_numbers", "markers", "lang", "verbatim", "quote", "shape", "label", "source"} {
		if entry.Has(k) {
			extra = append(extra, k)
		}
	}
	if len(extra) > 0 {
		sort.Strings(extra)
		return nil, fail("%s: field %s is a %s, checked by its template; take out %s", where, name, kind, joinStrings(extra))
	}
	entry.Set("kind", kind)
	entry.Set("node", pin[1])
	entry.Set("pin", pin[2])
	return entry, nil
}

func article(word string) string {
	if word != "" && strings.ContainsAny(word[:1], "aeiou") {
		return "an " + word
	}
	return "a " + word
}

func nest(templates map[string]*Template, digests map[string]string) (Catalog, error) {
	done := map[string]*Template{}
	var resolved func(name string, seen []string) (*Template, error)
	resolved = func(name string, seen []string) (*Template, error) {
		if t, ok := done[name]; ok {
			return t, nil
		}
		t := templates[name]
		chain := sha256.New()
		chain.Write([]byte(digests[name]))
		chain.Write([]byte{0})
		var fields []*Field
		nodes := false
		for _, item := range t.Fields {
			if item.Node == "" {
				fields = append(fields, item)
				continue
			}
			where := fmt.Sprintf("%s: field %s", t.Path, item.Name)
			target, ok := templates[item.Node]
			if !ok {
				return nil, fail("%s names %s, which is no template in %s/", where, item.Node, TemplatesFolder)
			}
			if in(item.Node, seen) || item.Node == name {
				return nil, fail("%s nests %s in a cycle (%s)", where, item.Node, strings.Join(append(append(append([]string{}, seen...), name), item.Node), " -> "))
			}
			if target.Version != item.Pin {
				return nil, fail("%s pins %s %s, but %s is at %s; pin %s@%s", where, item.Node, item.Pin, item.Node, target.Version, item.Node, target.Version)
			}
			wanted := []string{"block", "document"}
			if item.Kind == "register" {
				wanted = []string{"entry"}
			} else if item.Fence != "" {
				wanted = []string{"block"}
			}
			if !in(target.Kind, wanted) || target.IsFile() || len(target.Scope) > 0 {
				msg := fmt.Sprintf("%s: %s is %s", where, item.Node, article(target.Kind))
				if target.IsFile() {
					msg += " that shapes files"
				} else if len(target.Scope) > 0 {
					msg += " read after a marker"
				}
				if item.Kind == "register" {
					msg += "; a register"
				} else {
					msg += "; a node"
				}
				if item.Fence != "" {
					msg += " fence"
				}
				msg += " names " + article(strings.Join(wanted, " or ")) + " template, part of a document"
				return nil, &Error{msg}
			}
			nested, err := resolved(item.Node, append(append([]string{}, seen...), name))
			if err != nil {
				return nil, err
			}
			chain.Write([]byte(nested.Digest))
			chain.Write([]byte{0})
			copied := *item
			copied.nested = nested
			fields = append(fields, &copied)
			nodes = true
		}
		made := *t
		made.Fields = fields
		if nodes {
			made.Digest = "sha256:" + hex.EncodeToString(chain.Sum(nil))
		}
		done[name] = &made
		return &made, nil
	}
	out := Catalog{}
	for _, name := range sortedKeys(templates) {
		t, err := resolved(name, nil)
		if err != nil {
			return nil, err
		}
		out[name] = t
	}
	return out, nil
}
