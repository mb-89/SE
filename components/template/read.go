package template

import (
	"regexp"
	"strconv"
	"strings"
)

var (
	frontMatter         = regexp.MustCompile(`\A---\r?\n(?s:.*?)\r?\n---[ \t]*(?:\r?\n|\z)`)
	derivedKey          = regexp.MustCompile(`^derived_from[ \t]*:[ \t]*(.*?)[ \t]*$`)
	templateMarkerLine  = regexp.MustCompile(`(?m)^[ \t]*<!-- se:template [\w.-]+(?:/[\w.-]+)*/([\w-]+) [\w.+-]+ sha256:[0-9a-f]+ -->[ \t]*$`)
	heading             = regexp.MustCompile(`^(#{1,4})[ \t]+(.+?)[ \t]*#*[ \t]*$`)
	fence               = regexp.MustCompile("^[ \\t]*(`{3,}|~{3,})")
	comment             = regexp.MustCompile(`(?s)<!--.*?-->`)
	wholeCommentPattern = regexp.MustCompile(`^[ \t]*<!--.*-->[ \t]*$`)
	numbered            = regexp.MustCompile(`^(\d+)[.)](?:[ \t]+(.*?))?[ \t]*$`)
	bullet              = regexp.MustCompile(`^[-*+](?:[ \t]+(.*?))?[ \t]*$`)
	checkbox            = regexp.MustCompile(`^[-*+][ \t]+\[([ xX])\](?:[ \t]+(.*?))?[ \t]*$`)
	issueBullet         = regexp.MustCompile(`^[-*+][ \t]+`)
	objectLine          = regexp.MustCompile(`^[ \t]*(?:[-*+][ \t]+)?([^:\n]+?)[ \t]*:[ \t]*(.*?)[ \t]*$`)
	noResponse          = "_no response_"
)

// match is Python's pattern.match of a single line: `$` also matches before a closing "\n".
func match(p *regexp.Regexp, text string) []string {
	if m := p.FindStringSubmatch(text); m != nil {
		return m
	}
	if strings.HasSuffix(text, "\n") {
		return p.FindStringSubmatch(text[:len(text)-1])
	}
	return nil
}

// wholeComment reports whether text is one HTML comment alone on its line.
func wholeComment(text string) bool { return match(wholeCommentPattern, text) != nil }

// Part is a piece of a parsed body: preamble, prefix, gap, scope, suffix, front, head, data or text
// text, or a field, node or unknown section (its heading line, then its raw text).
type Part struct {
	Kind    string
	Raw     string
	Heading string
	Name    string
	fresh   bool // Python's raw None: a part render places, with no text of its own yet
}

// Document is a body read into a template's fields; Parts keeps its layout, so render writes the rest
// back as it was. Fields holds the fields present, the title among them.
type Document struct {
	Template string
	Fields   Object
	Parts    []Part
	Source   string
	Misses   map[string]string
	Read     Object
	Recorded string // the template version the body records; "" for none
}

func norm(text string) string {
	return joinWords(casefold(strip(strings.TrimRight(strip(text), ":"))))
}

func matches(item *Field, line string, level, base, own int) bool {
	if item.ExactHeading {
		return rstrip(line) == strings.Repeat("#", own)+" "+item.Heading
	}
	if level <= base {
		return false
	}
	m := heading.FindStringSubmatch(line)
	name, want := norm(m[2]), norm(item.Heading)
	return name == want || strings.HasPrefix(name, want+" (")
}

func bareLine(line string) string { return strings.TrimRight(line, "\r\n") }

// fenceStep moves a fence state over one line: it answers the new state and whether the line may be a
// heading (outside a fence and no fence line).
func fenceStep(state, line string) (string, bool) {
	m := fence.FindStringSubmatch(line)
	switch {
	case state == "" && m != nil:
		return m[1], false
	case state != "" && m != nil && strings.HasPrefix(m[1], state):
		return "", false
	case state == "":
		return "", true
	}
	return state, false
}

func split(text string, t *Template, base int) (string, []Part) {
	var preamble strings.Builder
	var parts []Part
	current := -1
	currentLevel := 0
	var currentRaw strings.Builder
	state := ""
	seen := map[string]bool{}
	closeCurrent := func() {
		if current >= 0 {
			parts[current].Raw = currentRaw.String()
		}
	}
	for _, line := range splitLines(text, true) {
		bare := bareLine(line)
		var head []string
		next, may := fenceStep(state, bare)
		state = next
		if may {
			head = heading.FindStringSubmatch(bare)
		}
		if head != nil && len(head[1]) > base {
			level := len(head[1])
			var found *Field
			for _, item := range t.Fields {
				if item.InBody() && !seen[item.Name] && matches(item, bare, level, base, t.Level()) {
					found = item
					break
				}
			}
			if found != nil || current < 0 || level <= currentLevel {
				closeCurrent()
				part := Part{Kind: "unknown", Heading: bare, Name: norm(head[2])}
				if found != nil {
					part.Kind, part.Name = "field", found.Name
					seen[found.Name] = true
				}
				parts = append(parts, part)
				current, currentLevel = len(parts)-1, level
				currentRaw.Reset()
				continue
			}
		}
		if current >= 0 {
			currentRaw.WriteString(line)
		} else {
			preamble.WriteString(line)
		}
	}
	closeCurrent()
	return preamble.String(), parts
}

func uncomment(text string, keepMarkers bool) string {
	if !keepMarkers {
		return comment.ReplaceAllString(text, "")
	}
	var out strings.Builder
	last := 0
	for _, loc := range comment.FindAllStringIndex(text, -1) {
		out.WriteString(text[last:loc[0]])
		whole := text[loc[0]:loc[1]]
		start := strings.LastIndex(text[:loc[0]], "\n") + 1
		end := strings.Index(text[loc[1]:], "\n")
		line := text[start:]
		if end >= 0 {
			line = text[start : loc[1]+end]
		}
		if !strings.Contains(whole, "\n") && wholeComment(line) {
			out.WriteString(whole)
		}
		last = loc[1]
	}
	out.WriteString(text[last:])
	return out.String()
}

type listItem struct {
	kind  string
	lines []string
}

func items(text string, pattern *regexp.Regexp, markers bool) [][2]string {
	var found []*listItem
	for _, line := range splitLines(text, false) {
		if markers && wholeComment(line) {
			found = append(found, &listItem{"marker", []string{strip(line)}})
			continue
		}
		m := match(pattern, line)
		if m == nil {
			if len(found) > 0 && found[len(found)-1].kind != "marker" {
				found[len(found)-1].lines = append(found[len(found)-1].lines, line)
			}
			continue
		}
		if pattern == checkbox {
			found = append(found, &listItem{m[1], []string{m[2]}})
		} else {
			found = append(found, &listItem{"item", []string{m[len(m)-1]}})
		}
	}
	var out [][2]string
	for _, item := range found {
		body := item.lines[0]
		if item.kind != "marker" {
			body = strip(strings.Join(item.lines, "\n"))
		}
		if body != "" {
			out = append(out, [2]string{item.kind, body})
		}
	}
	return out
}

// ValueOf is a field's value read from its section's raw text.
func ValueOf(item *Field, raw string) any {
	if item.Fence != "" {
		inner := splitLines(strings.Trim(raw, "\n"), false)
		if len(inner) > 0 {
			inner = inner[1:]
		}
		if len(inner) > 0 && fence.MatchString(inner[len(inner)-1]) {
			inner = inner[:len(inner)-1]
		}
		joined := strings.Join(inner, "\n")
		if notInInput(joined) {
			return strip(joined)
		}
		return strings.Trim(raw, "\n")
	}
	if item.Verbatim || item.Node != "" {
		return strings.Trim(raw, "\n")
	}
	text := uncomment(raw, item.Markers)
	if casefold(strip(text)) == noResponse {
		text = ""
	}
	if notInInput(text) {
		return strip(text)
	}
	switch item.Kind {
	case "line", "choice":
		for _, line := range splitLines(text, false) {
			if strip(line) != "" {
				return strip(line)
			}
		}
		return ""
	case "text":
		return strip(text)
	case "list":
		pattern := bullet
		if item.Numbered {
			pattern = numbered
		}
		list := []any{}
		for _, it := range items(text, pattern, item.Markers) {
			list = append(list, it[1])
		}
		return list
	case "checklist":
		list := []any{}
		for _, it := range items(text, checkbox, false) {
			list = append(list, Object{{"done", strings.ContainsAny(it[0], "xX")}, {"text", it[1]}})
		}
		return list
	case "issue":
		list := []any{}
		for _, line := range splitLines(text, false) {
			entry := issueBullet.ReplaceAllString(strip(line), "")
			if entry != "" {
				list = append(list, entry)
			}
		}
		return list
	case "object":
		found := Object{}
		for _, line := range splitLines(text, false) {
			if m := match(objectLine, line); m != nil {
				found.Set(m[1], m[2])
			}
		}
		return found
	}
	lines := splitLines(text, false)
	for i, line := range lines {
		opening := fence.FindStringSubmatch(line)
		if opening == nil {
			continue
		}
		var inner []string
		for _, later := range lines[i+1:] {
			closing := fence.FindStringSubmatch(later)
			if closing != nil && strings.HasPrefix(closing[1], opening[1]) {
				break
			}
			inner = append(inner, later)
		}
		return strings.Trim(strings.Join(inner, "\n"), "\n")
	}
	return strip(text)
}

// Parse reads body into the template's fields; title fills its title field where one is given.
func Parse(t *Template, body string, title *string) *Document {
	if t.IsAdapter() {
		fields := Object{}
		if title != nil {
			fields = Object{{"title", *title}}
		}
		return &Document{Template: t.Name, Fields: fields, Source: body, Read: fields.Copy(), Misses: map[string]string{}}
	}
	if t.Message != "" {
		found := fieldsOf(t.Message, body)
		if t.IsSnippet() {
			found = snippetFields(t, body)
		}
		return &Document{Template: t.Name, Fields: found, Source: body, Read: found.Copy(), Misses: map[string]string{}}
	}
	if t.writesFile() {
		return parseFile(t, body)
	}
	text := body
	if loc := frontMatter.FindStringIndex(body); loc != nil {
		text = body[loc[1]:]
	}
	doc := &Document{Template: t.Name, Fields: Object{}, Source: text, Recorded: markedVersion(t, body), Misses: map[string]string{}}
	var parts []Part
	region := text
	if len(t.Scope) > 0 {
		parts, region = scoped(t, text)
	} else {
		preamble, sections := split(text, t, 0)
		parts = append([]Part{{Kind: "preamble", Raw: preamble}}, sections...)
	}
	parts = fenced(t, parts)
	doc.Parts = parts
	preamble := ""
	for _, part := range parts {
		if part.Kind == "preamble" {
			preamble = part.Raw
			break
		}
	}
	for _, item := range t.Fields {
		if item.Source == "title" {
			if title != nil {
				doc.Fields.Set(item.Name, *title)
			}
		} else if item.Label != "" {
			label := regexp.MustCompile(`(?mi)^[ \t]*` + regexp.QuoteMeta(item.Label) + `[ \t]*:[ \t]*(.*?)[ \t]*$`)
			if m := label.FindStringSubmatch(preamble); m != nil {
				doc.Fields.Set(item.Name, m[1])
			}
		}
	}
	for _, part := range parts {
		if part.Kind == "field" || part.Kind == "node" {
			doc.Fields.Set(part.Name, ValueOf(t.Field(part.Name), part.Raw))
		}
	}
	doc.Read = doc.Fields.Copy()
	misses(t, doc, region)
	doc.Source = region
	return doc
}

func misses(t *Template, doc *Document, region string) {
	for _, item := range t.Fields {
		if !item.InBody() || doc.Fields.Has(item.Name) {
			continue
		}
		for _, line := range splitLines(region, false) {
			if m := heading.FindStringSubmatch(line); m != nil && norm(m[2]) == norm(item.Heading) {
				doc.Misses[item.Name] = line
				break
			}
		}
	}
}

func fenced(t *Template, parts []Part) []Part {
	for _, item := range t.Fields {
		if item.Fence == "" {
			continue
		}
		for i, part := range parts {
			if (part.Kind != "preamble" && part.Kind != "field" && part.Kind != "unknown") || part.Raw == "" {
				continue
			}
			start, end, ok := fenceSpan(part.Raw, item.Fence)
			if !ok {
				continue
			}
			before := part
			before.Raw = part.Raw[:start]
			made := append([]Part{}, parts[:i]...)
			made = append(made, before, Part{Kind: "node", Raw: part.Raw[start:end], Name: item.Name}, Part{Kind: "text", Raw: part.Raw[end:]})
			parts = append(made, parts[i+1:]...)
			break
		}
	}
	return parts
}

// fenceSpan is where the first fence whose info word is info starts and ends in text, its closing
// line's end included; an unclosed fence runs to the end.
func fenceSpan(text, info string) (int, int, bool) {
	offset, state, start := 0, "", -1
	for _, line := range splitLines(text, true) {
		bare := bareLine(line)
		m := fence.FindStringSubmatch(bare)
		if state == "" && m != nil {
			state = m[1]
			rest := words(strip(bare)[len(state):])
			if len(rest) > 0 && rest[0] == info {
				start = offset
			}
		} else if state != "" && m != nil && strings.HasPrefix(m[1], state) && strip(strip(bare)[len(m[1]):]) == "" {
			state = ""
			if start >= 0 {
				return start, offset + len(line), true
			}
		}
		offset += len(line)
	}
	if start >= 0 {
		return start, len(text), true
	}
	return 0, 0, false
}

func titleEnd(t *Template, text string) int {
	offset, state := 0, ""
	for _, line := range splitLines(text, true) {
		bare := bareLine(line)
		next, may := fenceStep(state, bare)
		state = next
		if may {
			if m := heading.FindStringSubmatch(bare); m != nil {
				level := len(m[1])
				if level == 1 {
					return offset + len(line)
				}
				for _, item := range t.Fields {
					if item.InBody() && matches(item, bare, level, 0, t.Level()) {
						return 0
					}
				}
			}
		}
		offset += len(line)
	}
	return 0
}

func parseFile(t *Template, body string) *Document {
	head := ""
	if loc := frontMatter.FindStringIndex(body); loc != nil {
		head = body[:loc[1]]
	}
	rest := body[len(head):]
	end := titleEnd(t, rest)
	title, rest := rest[:end], rest[end:]
	preamble, sections := split(rest, t, 0)
	parts := append([]Part{{Kind: "front", Raw: head}, {Kind: "head", Raw: title}, {Kind: "preamble", Raw: preamble}}, sections...)
	doc := &Document{Template: t.Name, Fields: Object{}, Source: rest, Parts: fenced(t, parts), Recorded: frontVersion(t, head), Misses: map[string]string{}}
	for _, part := range doc.Parts {
		if part.Kind == "field" || part.Kind == "node" {
			doc.Fields.Set(part.Name, ValueOf(t.Field(part.Name), part.Raw))
		}
	}
	doc.Read = doc.Fields.Copy()
	misses(t, doc, rest)
	return doc
}

// derivedFrom is templates.py `derived_from`: where front matter holds derived_from, from its key
// to the end of its last line, and the template and version it names ("" for both where it is no
// mapping of them); ok false where it holds none.
func derivedFrom(front string) (start, end int, template, version string, ok bool) {
	offset := 0
	lines := splitLines(front, true)
	for i, line := range lines {
		bare := strings.TrimRight(line, "\r\n")
		m := derivedKey.FindStringSubmatch(bare)
		if m == nil {
			offset += len(line)
			continue
		}
		end := offset + len(bare)
		text := "derived_from: " + m[1] + "\n"
		if m[1] == "" {
			after := offset + len(line)
			for _, following := range lines[i+1:] {
				if !(strings.HasPrefix(following, " ") || strings.HasPrefix(following, "\t")) || strip(following) == "" {
					break
				}
				kept := strings.TrimRight(following, "\r\n")
				text += kept + "\n"
				end = after + len(kept)
				after += len(following)
			}
		}
		named := [2]string{}
		if data, err := FrontData(text, "derived_from", 2); err == nil {
			if value, isObject := data.Value("derived_from").(Object); isObject {
				for j, key := range []string{"template", "version"} {
					switch v := value.Value(key).(type) {
					case string:
						named[j] = strip(v)
					case int:
						named[j] = strconv.Itoa(v)
					}
				}
			}
		}
		if named[0] == "" || named[1] == "" {
			named = [2]string{}
		}
		return offset, end, named[0], named[1], true
	}
	return 0, 0, "", "", false
}

// lastPart is the name after a template's repository, `<repository>/<name>`'s name.
func lastPart(name string) string {
	if at := strings.LastIndex(name, "/"); at >= 0 {
		return name[at+1:]
	}
	return name
}

// frontMatterTemplate is the template a file's front matter names in its derived_from, "" for none.
func frontMatterTemplate(body string) (string, bool) {
	loc := frontMatter.FindStringIndex(body)
	if loc == nil {
		return "", false
	}
	if _, _, named, _, ok := derivedFrom(body[:loc[1]]); ok && named != "" {
		return lastPart(named), true
	}
	return "", false
}

func frontKey(key string) *regexp.Regexp {
	return regexp.MustCompile(`(?m)^` + key + `[ \t]*:[ \t]*['"]?([^'"\r\n]*?)['"]?[ \t]*$`)
}

func frontVersion(t *Template, front string) string {
	if front == "" {
		return ""
	}
	_, _, named, version, ok := derivedFrom(front)
	if !ok || lastPart(named) != t.Name {
		return ""
	}
	return version
}

func markedVersion(t *Template, body string) string {
	for _, m := range templateMarkerLine.FindAllStringSubmatch(body, -1) {
		if m[1] == t.Name {
			return words(m[0])[3]
		}
	}
	return ""
}

func scoped(t *Template, text string) ([]Part, string) {
	after := str(t.Scope.Value("after"))
	if !t.Scope.Has("after") {
		after = ""
	}
	lines := splitLines(text, true)
	index := -1
	for i, line := range lines {
		if strip(line) == after {
			index = i
			break
		}
	}
	if index < 0 {
		return []Part{{Kind: "prefix", Raw: text}}, ""
	}
	prefix := strings.Join(lines[:index+1], "")
	rest := lines[index+1:]
	want := ""
	if t.Scope.Has("section") {
		want = norm(str(t.Scope.Value("section")))
	}
	start, level, state := -1, 0, ""
	for i, line := range rest {
		next, may := fenceStep(state, line)
		state = next
		if !may {
			continue
		}
		if m := heading.FindStringSubmatch(bareLine(line)); m != nil && norm(m[2]) == want {
			start, level = i, len(m[1])
			break
		}
	}
	if start < 0 {
		return []Part{{Kind: "prefix", Raw: prefix}, {Kind: "gap", Raw: strings.Join(rest, "")}}, ""
	}
	end := len(rest)
	state = ""
	for i := start + 1; i < len(rest); i++ {
		next, may := fenceStep(state, rest[i])
		state = next
		if !may {
			continue
		}
		if m := heading.FindStringSubmatch(bareLine(rest[i])); m != nil && len(m[1]) <= level {
			end = i
			break
		}
	}
	region := strings.Join(rest[start+1:end], "")
	preamble, sections := split(region, t, t.Level()-1)
	parts := []Part{{Kind: "prefix", Raw: prefix}, {Kind: "gap", Raw: strings.Join(rest[:start], "")},
		{Kind: "scope", Heading: bareLine(rest[start])}, {Kind: "preamble", Raw: preamble}}
	parts = append(parts, sections...)
	parts = append(parts, Part{Kind: "suffix", Raw: strings.Join(rest[end:], "")})
	return parts, strings.Join(rest[start:end], "")
}

// fieldsOf reads a message line: its fields where text is one line of message, stripped; none else.
func fieldsOf(message, text string) Object {
	var pattern strings.Builder
	last := 0
	var names []string
	for _, loc := range placeholderRef.FindAllStringSubmatchIndex(message, -1) {
		pattern.WriteString(regexp.QuoteMeta(message[last:loc[0]]))
		pattern.WriteString(`(.+?)`)
		names = append(names, message[loc[2]:loc[3]])
		last = loc[1]
	}
	pattern.WriteString(regexp.QuoteMeta(message[last:]))
	m := regexp.MustCompile(`^(?:` + pattern.String() + `)\z`).FindStringSubmatch(strip(text))
	found := Object{}
	if m == nil {
		return found
	}
	for i, name := range names {
		found.Set(name, strip(m[i+1]))
	}
	return found
}
