package template

// A snippet is a message of several lines (scripts/interfaces.py "A snippet"): a rows field is
// written as one line per row, a case field as one of its lines. The Python engine owns the
// format; this file answers as it does, held to its answers by the shared cases.

import (
	"sort"
	"strings"
)

// IsSnippet reports whether the template's message has several lines.
func (t *Template) IsSnippet() bool { return strings.Contains(t.Message, "\n") }

// snippetProblem is what is wrong with a snippet of fields, or "" (interfaces.py snippet_problem).
func snippetProblem(message string, fields []*Field) string {
	inCases := map[string]bool{}
	var caseNames []string
	for _, f := range fields {
		for _, pair := range f.Cases {
			for _, name := range placeholders(str(pair.Value)) {
				if !inCases[name] {
					caseNames = append(caseNames, name)
				}
				inCases[name] = true
			}
		}
	}
	sort.Strings(caseNames)
	named := append(placeholders(message), caseNames...)
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
		return "message names " + n + "; it names each field once, in its lines or a case's: " + joinStrings(names)
	}
	lines := map[string]bool{}
	for _, line := range strings.Split(message, "\n") {
		lines[strip(line)] = true
	}
	for _, f := range fields {
		kind := f.Kind
		if f.Source != "" || f.Label != "" || f.Node != "" {
			kind = ""
		}
		if !in(kind, []string{"line", "choice", "rows", "case"}) {
			return "field " + f.Name + " of a snippet is a line, a choice, rows or a case"
		}
		if kind == "rows" && !lines["{"+f.Name+"}"] {
			return "rows field " + f.Name + " stands alone on its line, {" + f.Name + "}"
		}
		if inCases[f.Name] && kind != "line" {
			return "field " + f.Name + " named in a case is a line"
		}
	}
	return ""
}

func (t *Template) rowsOf(name string) (string, bool) {
	for _, f := range t.Fields {
		if f.Kind == "rows" && f.Name == name {
			return f.Row, true
		}
	}
	return "", false
}

// caseIn is the case field the message line names, if any.
func (t *Template) caseIn(line string) *Field {
	for _, f := range t.Fields {
		if f.Kind == "case" && strings.Contains(line, "{"+f.Name+"}") {
			return f
		}
	}
	return nil
}

// snippetText writes a snippet as interfaces.py `text` does.
func snippetText(t *Template, values Object) string {
	var out []string
	for _, line := range strings.Split(t.Message, "\n") {
		if m := placeholderRef.FindStringSubmatch(strip(line)); m != nil && m[0] == strip(line) {
			if row, ok := t.rowsOf(m[1]); ok {
				v, _ := values.Get(m[1])
				if list, isList := v.([]any); isList {
					for _, entry := range list {
						if o, isObject := entry.(Object); isObject {
							out = append(out, messageLine(row, o))
						}
					}
				}
				continue
			}
		}
		for _, f := range t.Fields {
			if f.Kind != "case" || !strings.Contains(line, "{"+f.Name+"}") {
				continue
			}
			chosen := ""
			v, _ := values.Get(f.Name) // nil where missing: Python's str(None)
			if text, has := f.Cases.Get(str(v)); has {
				chosen = str(text)
			}
			line = strings.ReplaceAll(line, "{"+f.Name+"}", chosen)
		}
		out = append(out, messageLine(line, values))
	}
	return strings.Join(out, "\n")
}

// snippetFields reads a snippet back as interfaces.py `snippet_fields` does: none where the
// text is not the snippet.
func snippetFields(t *Template, written string) Object {
	lines := strings.Split(strings.TrimRight(written, "\n"), "\n")
	found := Object{}
	at := 0
	for _, line := range strings.Split(t.Message, "\n") {
		if m := placeholderRef.FindStringSubmatch(strip(line)); m != nil && m[0] == strip(line) {
			if row, ok := t.rowsOf(m[1]); ok {
				taken := []any{}
				for at < len(lines) {
					got, matched := matchLine(row, lines[at])
					if !matched {
						break
					}
					taken = append(taken, got)
					at++
				}
				found.Set(m[1], taken)
				continue
			}
		}
		if at >= len(lines) {
			return Object{}
		}
		type option struct{ key, line string }
		options := []option{{"", line}}
		field := t.caseIn(line)
		if field != nil {
			options = nil
			for _, pair := range field.Cases {
				options = append(options, option{pair.Key, strings.ReplaceAll(line, "{"+field.Name+"}", str(pair.Value))})
			}
		}
		matchedAny := false
		for _, o := range options {
			var got Object
			matched := false
			if !placeholderRef.MatchString(o.line) {
				matched = strip(o.line) == strip(lines[at])
				got = Object{}
			} else {
				got, matched = matchLine(o.line, lines[at])
			}
			if matched {
				for _, pair := range got {
					found.Set(pair.Key, pair.Value)
				}
				if field != nil {
					found.Set(field.Name, o.key)
				}
				matchedAny = true
				break
			}
		}
		if !matchedAny {
			return Object{}
		}
		at++
	}
	for _, rest := range lines[at:] {
		if strip(rest) != "" {
			return Object{}
		}
	}
	return found
}

// matchLine is fieldsOf with whether the line matched.
func matchLine(message, text string) (Object, bool) {
	found := fieldsOf(message, text)
	if len(found) == 0 && len(placeholders(message)) > 0 {
		return found, false
	}
	return found, true
}
