package template

import (
	"fmt"
	"regexp"
	"strings"
)

const schemaDialect = "https://json-schema.org/draft/2020-12/schema"

func format(item *Field, value any, first int) string {
	if s, ok := value.(string); item.Verbatim || item.Node != "" || item.Kind == "line" || item.Kind == "choice" || item.Kind == "text" || (ok && notInInput(s)) {
		return str(value)
	}
	switch item.Kind {
	case "list":
		var lines []string
		number := first
		for _, entry := range listOf(value) {
			text := str(entry)
			switch {
			case wholeComment(text):
				lines = append(lines, text)
			case item.Numbered:
				lines = append(lines, fmt.Sprintf("%d. %s", number, text))
				number++
			default:
				lines = append(lines, "- "+text)
			}
		}
		return strings.Join(lines, "\n")
	case "checklist":
		var lines []string
		for _, entry := range listOf(value) {
			mark, text := " ", ""
			if o, ok := entry.(Object); ok {
				if truthy(o.Value("done")) {
					mark = "x"
				}
				text = ""
				if v, ok := o.Get("text"); ok {
					text = str(v)
				}
			} else {
				text = str(entry)
			}
			lines = append(lines, fmt.Sprintf("- [%s] %s", mark, text))
		}
		return strings.Join(lines, "\n")
	case "issue":
		var lines []string
		for _, entry := range listOf(value) {
			lines = append(lines, str(entry))
		}
		return strings.Join(lines, "\n")
	case "object":
		var lines []string
		if o, ok := value.(Object); ok {
			for _, pair := range o {
				lines = append(lines, pair.Key+": "+str(pair.Value))
			}
		}
		return strings.Join(lines, "\n")
	}
	return fmt.Sprintf("```%s\n%s\n```", item.Lang, str(value))
}

func listOf(value any) []any {
	switch x := value.(type) {
	case []any:
		return x
	case string:
		out := make([]any, 0, len(x))
		for _, r := range x {
			out = append(out, string(r))
		}
		return out
	case Object:
		out := make([]any, len(x))
		for i, pair := range x {
			out[i] = pair.Key
		}
		return out
	}
	return nil
}

func count(item *Field, value any) int {
	list, ok := value.([]any)
	if item.Kind != "list" || !item.Numbered || !ok {
		return 0
	}
	n := 0
	for _, entry := range list {
		if !wholeComment(str(entry)) {
			n++
		}
	}
	return n
}

func withoutMarkers(text string) string {
	var kept strings.Builder
	for _, line := range splitLines(text, true) {
		if strip(line) != FleetMarker && !templateMarkerLine.MatchString(bareLine(line)) {
			kept.WriteString(line)
		}
	}
	return kept.String()
}

func withTemplate(front string, t *Template) string {
	lines := t.frontLines()
	if front == "" {
		var b strings.Builder
		b.WriteString("---\n")
		for _, l := range lines {
			b.WriteString(l[0] + ": " + l[1] + "\n")
		}
		b.WriteString("---\n\n")
		return b.String()
	}
	newline := "\n"
	if strings.Contains(front, "\r\n") {
		newline = "\r\n"
	}
	after := -1
	for _, l := range lines {
		closing := strings.LastIndex(strings.TrimRight(front, "\r\n"), "\n") + 1
		line := l[0] + ": " + l[1]
		pattern := frontTemplate
		if l[0] != "template" {
			pattern = frontKey(l[0])
		}
		if loc := pattern.FindStringIndex(front[:closing]); loc != nil {
			front = front[:loc[0]] + line + front[loc[1]:]
			after = loc[0] + len(line) + len(newline)
		} else {
			at := closing
			if after >= 0 {
				at = after
			}
			front = front[:at] + line + newline + front[at:]
			after = at + len(line) + len(newline)
		}
	}
	return front
}

// Answer gives field values as render takes them: an object field given as the schema's list of
// {"key", "value"} pairs becomes its mapping.
func Answer(t *Template, values Object) Object {
	given := values.Copy()
	for _, item := range t.Fields {
		list, ok := given.Value(item.Name).([]any)
		if item.Kind != "object" || !ok {
			continue
		}
		pairs := true
		for _, p := range list {
			o, isObject := p.(Object)
			if !isObject || len(o) != 2 || !o.Has("key") || !o.Has("value") {
				pairs = false
			}
		}
		if !pairs {
			continue
		}
		mapped := Object{}
		for _, p := range list {
			o := p.(Object)
			mapped.Set(str(o.Value("key")), str(o.Value("value")))
		}
		given.Set(item.Name, mapped)
	}
	return given
}

func emptyValue(v any) bool {
	switch x := v.(type) {
	case nil:
		return true
	case string:
		return x == ""
	case []any:
		return len(x) == 0
	case Object:
		return len(x) == 0
	}
	return false
}

// Render writes the document as canonical Markdown (scripts/templates.py's docstring, "Writing").
func Render(t *Template, doc *Document) (string, error) {
	if t.IsAdapter() {
		if doc == nil {
			return "", fail("templates: %s is an adapter and has no fields to render; the command that writes it writes its body", t.Name)
		}
		return doc.Source, nil
	}
	values := doc.Fields
	if t.Message != "" {
		return messageLine(t.Message, values) + "\n", nil
	}
	marker := t.MarkerLine()
	hashes := strings.Repeat("#", t.Level())
	parts := append([]Part{}, doc.Parts...)
	hasScope := false
	for _, p := range parts {
		if p.Kind == "scope" {
			hasScope = true
		}
	}
	if len(t.Scope) > 0 && !hasScope {
		var data strings.Builder
		for _, p := range parts {
			if p.Kind == "prefix" || p.Kind == "gap" {
				data.WriteString(p.Raw)
			}
		}
		after := str(t.Scope.Value("after"))
		text := data.String()
		if in(after, splitLines(text, false)) {
			var kept []string
			for _, line := range splitLines(text, false) {
				if strip(line) != after {
					kept = append(kept, line)
				}
			}
			text = strings.Join(kept, "\n")
		}
		parts = nil
		if strip(text) != "" {
			parts = append(parts, Part{Kind: "data", Raw: endLine(text)})
		}
		parts = append(parts, Part{Kind: "prefix", Raw: after + "\n"}, Part{Kind: "gap"},
			Part{Kind: "scope", Heading: "## " + str(t.Scope.Value("section"))}, Part{Kind: "preamble"}, Part{Kind: "suffix"})
	} else if len(parts) == 0 {
		if t.IsFile() {
			parts = []Part{{Kind: "front"}, {Kind: "head"}, {Kind: "preamble"}}
		} else {
			parts = []Part{{Kind: "preamble"}}
		}
	}
	placed := map[string]bool{}
	for _, p := range parts {
		if p.Kind == "field" || p.Kind == "node" {
			placed[p.Name] = true
		}
	}
	names := make([]string, len(t.Fields))
	for i, f := range t.Fields {
		names[i] = f.Name
	}
	for position, item := range t.Fields {
		if !(item.InBody() || item.Fence != "") || placed[item.Name] || emptyValue(values.Value(item.Name)) {
			continue
		}
		earlier := map[string]bool{}
		for _, n := range names[:position] {
			earlier[n] = true
		}
		index := -1
		for i, p := range parts {
			if (p.Kind == "field" || p.Kind == "node") && earlier[p.Name] {
				index = i
			}
		}
		if index < 0 {
			for i, p := range parts {
				if p.Kind == "preamble" || p.Kind == "scope" {
					index = i
				}
			}
		}
		part := Part{Kind: "field", Name: item.Name, Heading: hashes + " " + item.Heading, fresh: true}
		if item.Fence != "" {
			part.Kind, part.Heading = "node", ""
		}
		parts = append(parts[:index+1], append([]Part{part}, parts[index+1:]...)...)
		placed[item.Name] = true
	}
	var out []string
	number := 1
	for _, part := range parts {
		switch part.Kind {
		case "front":
			out = append(out, withTemplate(part.Raw, t))
		case "head":
			out = append(out, withoutMarkers(part.Raw))
		case "prefix":
			if part.Raw != "" {
				out = append(out, endLine(part.Raw))
			} else {
				out = append(out, "")
			}
			out = append(out, marker+"\n")
		case "gap":
			out = append(out, withoutMarkers(part.Raw))
		case "scope":
			out = append(out, part.Heading+"\n")
		case "preamble":
			preamble := labels(t, doc, withoutMarkers(part.Raw))
			switch {
			case t.IsFile():
				out = append(out, preamble)
			case len(t.Scope) == 0:
				out = append(out, FleetMarker+"\n"+marker+"\n")
				preamble = strings.TrimLeft(preamble, "\n")
				if strip(preamble) != "" {
					out = append(out, "\n"+endLine(preamble))
				} else {
					out = append(out, "\n")
				}
			default:
				if strip(preamble) != "" {
					out = append(out, preamble)
				} else {
					out = append(out, "\n")
				}
			}
		case "suffix", "data", "text":
			text := part.Raw
			if part.Kind == "data" && strip(part.Raw) != "" {
				text += "\n"
			}
			out = append(out, text)
		case "node":
			value, ok := values.Get(part.Name)
			if !ok {
				continue
			}
			if read, had := doc.Read.Get(part.Name); !part.fresh && had && equal(read, value) {
				out = append(out, part.Raw)
			} else {
				text := str(value)
				if notInInput(value) {
					text = fmt.Sprintf("```%s\n%s\n```", t.Field(part.Name).Fence, str(value))
				}
				if len(out) == 0 || strings.HasSuffix(out[len(out)-1], "\n\n") {
					out = append(out, text+"\n\n")
				} else {
					out = append(out, "\n"+text+"\n\n")
				}
			}
		case "unknown":
			if t.KeepUnknown {
				out = append(out, part.Heading+"\n"+part.Raw)
			}
		default:
			item := t.Field(part.Name)
			value, ok := values.Get(part.Name)
			if !ok {
				continue
			}
			used := count(item, value)
			if item.Numbered && !item.ContinueNumbers {
				number = 1
			}
			if read, had := doc.Read.Get(part.Name); !part.fresh && had && equal(read, value) {
				out = append(out, hashes+" "+item.Heading+"\n"+part.Raw)
			} else {
				out = append(out, hashes+" "+item.Heading+"\n\n"+format(item, value, number)+"\n\n")
			}
			number += used
		}
		if n := len(out); n > 0 && out[n-1] != "" && !strings.HasSuffix(out[n-1], "\n") {
			out[n-1] += "\n"
		}
	}
	return strings.TrimRight(strings.Join(out, ""), "\n") + "\n", nil
}

// RenderFields writes the document a template's fields fill.
func RenderFields(t *Template, values Object) (string, error) {
	if t.IsAdapter() {
		return Render(t, nil)
	}
	return Render(t, &Document{Template: t.Name, Fields: Answer(t, values), Read: Object{}, Misses: map[string]string{}})
}

func labels(t *Template, doc *Document, preamble string) string {
	for _, item := range t.Fields {
		if item.Label == "" || !doc.Fields.Has(item.Name) {
			continue
		}
		value := doc.Fields.Value(item.Name)
		if read, had := doc.Read.Get(item.Name); had && equal(read, value) && len(doc.Parts) > 0 {
			continue
		}
		line := item.Label + ": " + str(value)
		pattern := regexp.MustCompile(`(?mi)^[ \t]*` + regexp.QuoteMeta(item.Label) + `[ \t]*:.*$`)
		if loc := pattern.FindStringIndex(preamble); loc != nil {
			preamble = preamble[:loc[0]] + line + preamble[loc[1]:]
		} else {
			rest := "\n"
			if strip(preamble) != "" {
				rest = preamble
			}
			preamble = "\n" + line + "\n" + rest
		}
	}
	return preamble
}

func messageLine(message string, values Object) string {
	return placeholderRef.ReplaceAllStringFunc(message, func(m string) string {
		name := m[1 : len(m)-1]
		v, ok := values.Get(name)
		if !ok {
			return ""
		}
		return joinWords(str(v))
	})
}

// Draft is the empty template as Markdown, each field's says as a comment.
func Draft(t *Template) string {
	if t.IsAdapter() {
		return fmt.Sprintf("<!-- %s: %s -->\n<!-- %s -->\n", t.Name, t.Says, checkedBy(t))
	}
	if t.Message != "" {
		lines := []string{t.Message}
		for _, item := range t.Fields {
			lines = append(lines, fmt.Sprintf("<!-- %s: %s -->", item.Name, item.Says))
		}
		return strings.Join(lines, "\n") + "\n"
	}
	var lines []string
	switch {
	case t.IsFile():
		lines = append(lines, "---")
		for _, l := range t.frontLines() {
			lines = append(lines, l[0]+": "+l[1])
		}
		lines = append(lines, "---", "")
	case len(t.Scope) > 0:
		lines = append(lines, str(t.Scope.Value("after")), t.MarkerLine(), "## "+str(t.Scope.Value("section")), "")
	default:
		lines = append(lines, FleetMarker, t.MarkerLine(), "")
	}
	hashes := strings.Repeat("#", t.Level())
	for _, item := range t.Fields {
		if item.Source == "title" {
			lines = append(lines, fmt.Sprintf("<!-- title: %s -->", item.Says), "")
		} else if item.Label != "" {
			lines = append(lines, fmt.Sprintf("%s: <!-- %s -->", item.Label, item.Says), "")
		}
	}
	for _, item := range t.Fields {
		if item.InBody() {
			lines = append(lines, hashes+" "+item.Heading, "", fmt.Sprintf("<!-- %s -->", item.Says), "")
		}
	}
	return strings.TrimRight(strings.Join(lines, "\n"), "\n") + "\n"
}

// DraftFields is the empty template as data: each field's empty value and its says, its shape and
// the template's JSON Schema.
func DraftFields(t *Template) Object {
	fields, says, shapes := Object{}, Object{}, Object{}
	for _, item := range t.Fields {
		switch item.Kind {
		case "list", "issue", "checklist":
			fields.Set(item.Name, []any{})
		case "object":
			fields.Set(item.Name, Object{})
		default:
			fields.Set(item.Name, "")
		}
		says.Set(item.Name, item.Says)
		shapes.Set(item.Name, FieldShape(item))
	}
	return Object{{"template", t.Name}, {"says", t.Says}, {"fields", fields}, {"field_says", says}, {"field_shape", shapes}, {"schema", Schema(t)}}
}

// FieldShape is a field's shape as draft --json gives it: its kind, and each key it sets.
func FieldShape(item *Field) Object {
	shape := Object{{"kind", item.Kind}}
	add := func(key string, v any) {
		if truthy(v) {
			shape.Set(key, v)
		}
	}
	add("heading", item.Heading)
	add("required", item.Required)
	add("none_ok", item.NoneOK)
	if len(item.Choices) > 0 {
		shape.Set("choices", toAny(item.Choices))
	}
	add("max_words", item.MaxWords)
	add("first_sentence_chars", item.FirstSentenceChars)
	add("numbered", item.Numbered)
	add("label", item.Label)
	add("source", item.Source)
	add("quote", item.Quote)
	return shape
}

func pairsSchema(keys ...string) Object {
	props := Object{}
	for _, key := range keys {
		props.Set(key, Object{{"type", "string"}})
	}
	return Object{{"type", "object"}, {"properties", props}, {"required", toAny(keys)}, {"additionalProperties", false}}
}

func property(item *Field) Object {
	strings := Object{{"type", "array"}, {"items", Object{{"type", "string"}}}}
	var made Object
	switch item.Kind {
	case "choice":
		made = Object{{"type", "string"}, {"enum", toAny(append(append([]string{}, item.Choices...), NotInInput))}}
	case "list", "issue":
		made = strings
	case "checklist":
		made = Object{{"type", "array"}, {"items", Object{{"type", "object"}, {"properties", Object{{"done", Object{{"type", "boolean"}}}, {"text", Object{{"type", "string"}}}}}, {"required", []any{"done", "text"}}, {"additionalProperties", false}}}}
	case "object":
		made = Object{{"type", "array"}, {"items", pairsSchema("key", "value")}}
	default:
		made = Object{{"type", "string"}}
	}
	return append(made, Pair{"description", item.Says})
}

// Schema is a JSON Schema 2020-12 of the template's fields, written with the keywords strict tool
// use takes alone.
func Schema(t *Template) Object {
	props := Object{}
	required := []any{}
	for _, item := range t.Fields {
		props.Set(item.Name, property(item))
		if item.Required {
			required = append(required, item.Name)
		}
	}
	return Object{{"$schema", schemaDialect}, {"type", "object"}, {"properties", props}, {"required", required}, {"additionalProperties", false}}
}

func checkedBy(t *Template) string {
	checker := t.Checker
	if checker == "" {
		checker = "none"
	}
	parts := []string{"checker " + checker}
	if truthy(t.Adapter.Value("title_rule")) {
		parts = append(parts, "title "+str(t.Adapter.Value("title_rule")))
	}
	if lines, ok := t.Adapter.Value("lines").([]any); ok && len(lines) > 0 {
		parts = append(parts, fmt.Sprintf("%d lines", len(lines)))
	}
	tail := ""
	if !(len(parts) > 1 || t.Checker != "") {
		tail = " (no field required)"
	}
	return joinStrings(parts) + tail
}

// ListLine is the one line list gives the template: its name, reader, actions, paths, an
// adapter's checker, and what it says.
func ListLine(t *Template) string {
	actions := joinStrings(t.Actions)
	if actions == "" {
		actions = "a node of a document"
	}
	line := fmt.Sprintf("%s (%s): %s: ", t.Name, t.Reader, actions)
	if len(t.Paths) > 0 {
		line += joinStrings(t.Paths) + ": "
	}
	if t.IsAdapter() {
		line += checkedBy(t) + ": "
	}
	return line + t.Says
}
